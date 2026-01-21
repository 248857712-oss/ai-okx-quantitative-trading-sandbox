import logging
import os
import time
import datetime
import pandas as pd
import ta
import requests
import json
import hashlib
import hmac
import base64
from urllib.parse import urlencode, quote
import ccxt

# 导入优化后的工具类
from config_utils import load_config
from log_utils import init_logger, trade_logger
from trade_utils import save_trade_record, get_trade_statistics
from gb_stop_loss_take_profit import GBSLTPModel

# 加载配置并校验
config = load_config()
PROXY_SETTINGS = config["proxy"]


# ================= OKX现货杠杆API客户端（最终优化版） =================
class OKXAPIClient:
    def __init__(self, api_key, api_secret, passphrase, is_sim=True):
        # CCXT初始化（强制现货类型）
        self.okx_ccxt = ccxt.okx({
            'apiKey': api_key,
            'secret': api_secret,
            'password': passphrase,
            'enableRateLimit': True,
            'sandbox': is_sim,
            'proxies': PROXY_SETTINGS,
            'options': {'defaultType': 'spot'}
        })
        self.okx_ccxt.load_markets()

        # 原生API配置
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.base_url = "https://www.okx.com"
        self.sim = is_sim
        self.session = requests.Session()
        self.session.proxies = PROXY_SETTINGS
        requests.packages.urllib3.disable_warnings()

    def _get_timestamp(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        return now.isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    def _sign(self, timestamp, method, request_path, body=""):
        if isinstance(body, dict):
            body = json.dumps(body, separators=(',', ':')) if body else ""
        message = f"{timestamp}{method}{request_path}{body}"
        mac = hmac.new(
            self.api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode('utf-8')

    def request(self, method, request_path, params=None, data=None):
        timestamp = self._get_timestamp()
        method = method.upper()
        url = f"{self.base_url}{request_path}"
        params = params or {}
        data = data or {}

        if method == "GET" and params:
            url += "?" + urlencode(params, safe='=&')
            body = ""
        elif method == "POST" and data:
            body = json.dumps(data, separators=(',', ':'))
        else:
            body = ""

        signature = self._sign(timestamp, method, request_path, body)
        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }
        if self.sim:
            headers["x-simulated-trading"] = "1"

        try:
            if method == "GET":
                response = self.session.get(url, headers=headers, timeout=20, verify=False)
            elif method == "POST":
                response = self.session.post(url, data=body, headers=headers, timeout=20, verify=False)
            else:
                return None
            response.raise_for_status()
            result = response.json()
            return result["data"] if result["code"] == "0" else None
        except Exception as e:
            logging.error(f"API请求失败: {str(e)[:100]}")
            return None

    # 获取现货实时价
    def get_ticker_price(self, symbol):
        try:
            ticker = self.okx_ccxt.fetch_ticker(symbol)
            return float(ticker['last'])
        except Exception as e:
            data = self.request("GET", "/api/v5/market/ticker", params={"instId": symbol, "instType": "SPOT"})
            return float(data[0]['last']) if data else 0.0

    # 获取现货账户余额
    def get_account_balance(self):
        try:
            balance_data = self.request("GET", "/api/v5/account/balance", params={"ccy": "USDT"})
            if balance_data and len(balance_data) > 0:
                avail_usdt = float(balance_data[0]['availBal'])
                logging.info(f"✅ 现货账户可用USDT: {avail_usdt}")
                return avail_usdt
            return 0.0
        except Exception as e:
            logging.error(f"余额获取失败: {str(e)}")
            return 0.0

    # 设置现货杠杆
    def set_leverage(self, symbol, leverage):
        try:
            data = {
                "instId": symbol,
                "instType": "SPOT",
                "lever": str(leverage),
                "mgnMode": "cross"
            }
            result = self.request("POST", "/api/v5/account/set-leverage", data=data)
            if result:
                logging.info(f"✅ 现货杠杆设置成功 | {leverage}倍")
            else:
                logging.warning(f"⚠️ 现货杠杆设置失败")
        except Exception as e:
            logging.error(f"杠杆设置异常: {str(e)[:80]}")


# ================= 现货杠杆策略主类（最终优化版） =================
class OKXSpotMarginTrader:
    def __init__(self, config):
        self.config = config
        self.symbol = config["okx"]["symbol"]
        self.leverage = config["strategy"]["leverage"]
        self.position_ratio = config["strategy"]["position_ratio"]
        self.lr_weight = config["strategy"]["lr_weight"]
        self.rf_weight = config["strategy"]["rf_weight"]
        self.vote_threshold = config["strategy"]["vote_threshold"]
        self.tp_prob_threshold = config["strategy"]["tp_prob_threshold"]
        self.sl_prob_threshold = config["strategy"]["sl_prob_threshold"]
        self.cycle_interval = config["strategy"]["cycle_interval"]

        # 从配置读取布林带参数
        self.boll_window = config["strategy"]["boll_window"]
        self.boll_dev = config["strategy"]["boll_dev"]

        # 策略参数
        self.min_profit_threshold = 0.001
        self.min_loss_threshold = 0.001
        self.target_profit_ratio = 0.005
        self.min_profit_risk_ratio = 1.5

        # 持仓状态
        self.position = 0  # 0无持仓 1有持仓
        self.entry_price = None
        self.hold_amount = 0.0
        self.last_price = 0.0
        self.boll_lower = 0.0  # 布林下轨存储

        # 初始化日志、客户端、模型
        self.logger = init_logger(config["log"]["log_path"], config["log"]["log_level"])
        self.client = OKXAPIClient(
            config["okx"]["api_key"],
            config["okx"]["api_secret"],
            config["okx"]["api_passphrase"],
            config["okx"]["is_sim"]
        )
        self.lr = __import__('sklearn.linear_model').linear_model.LogisticRegression(random_state=42, max_iter=200)
        self.rf = __import__('sklearn.ensemble').ensemble.RandomForestClassifier(n_estimators=100, max_depth=6,
                                                                                 random_state=42)
        self.sltp_model = GBSLTPModel(random_state=42)
        self.trained = False

        # K线周期映射
        self.timeframe_mapping = {
            '1m': '1M', '5m': '5M', '15m': '15M', '30m': '30M',
            '1h': '1H', '2h': '2H', '4h': '4H', '6h': '6H',
            '12h': '12H', '1d': '1D', '1w': '1W'
        }

        self.logger.info("✅ 现货杠杆策略初始化完成")
        self.logger.info(f"交易对: {self.symbol} | 杠杆: {self.leverage}倍 | 仓位比例: {self.position_ratio * 100}%")

    # 获取实时价
    def get_realtime_price(self):
        try:
            realtime_price = self.client.get_ticker_price(self.symbol)
            if realtime_price > 0:
                self.last_price = realtime_price
                self.logger.info(f"✅ 实时价更新 | {self.symbol} = {realtime_price:.2f} USDT")
            return realtime_price
        except Exception as e:
            self.logger.error(f"实时价获取失败: {str(e)[:100]}")
            return self.last_price if self.last_price > 0 else 0.0

    # 计算下单数量
    def calculate_order_amount(self, realtime_price=None):
        balance = self.client.get_account_balance()
        if balance <= 0:
            self.logger.error("❌ 账户余额不足")
            return 0.0

        current_price = realtime_price or self.get_realtime_price()
        if current_price <= 0:
            self.logger.error("❌ 实时价无效")
            return 0.0

        order_value = balance * self.position_ratio * self.leverage
        order_amount = order_value / current_price
        order_amount = round(order_amount, 6)  # BTC精度6位

        min_amount = 0.000001
        if order_amount < min_amount:
            self.logger.warning(f"⚠️ 下单量过小，强制设为{min_amount}")
            order_amount = min_amount

        self.logger.info(f"📊 仓位计算 | 余额: {balance} USDT | 下单金额: {order_value:.2f} USDT | 数量: {order_amount}")
        return order_amount

    # 获取K线数据
    def fetch_ohlcv(self, tf='1h', limit=300):
        try:
            okx_tf = self.timeframe_mapping.get(tf, '1H')
            params = {'instId': self.symbol, 'bar': okx_tf, 'limit': limit, 'instType': 'SPOT'}
            data = self.client.request("GET", "/api/v5/market/history-candles", params=params)
            if not data:
                self.logger.error("❌ K线数据为空")
                return pd.DataFrame()

            df = pd.DataFrame(data, columns=[
                'ts', 'open', 'high', 'low', 'close', 'vol', 'volCcy', 'volCcyQuote', 'confirm'
            ])
            for col in ['open', 'high', 'low', 'close', 'vol']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df['ts'] = pd.to_datetime(pd.to_numeric(df['ts']), unit='ms')
            df = df.dropna().sort_values('ts').reset_index(drop=True)
            self.logger.info(f"✅ 获取K线 | 周期:{tf} | 数量:{len(df)}")
            return df
        except Exception as e:
            self.logger.error(f"K线获取失败: {str(e)[:100]}")
            return pd.DataFrame()

    # 模型训练
    @trade_logger
    def train(self, df):
        if df.empty:
            self.logger.error("❌ 训练数据为空")
            return
        df = df.copy()
        df['ret'] = (df['close'] - df['open']) / df['open']
        df['range'] = (df['high'] - df['low']) / df['open']
        df['vol_ratio'] = df['vol'] / df['vol'].rolling(20).mean()
        df['y'] = (df['close'].shift(-1) > df['close']).astype(int)
        df = df.dropna()
        if len(df) < 10:
            self.logger.error(f"❌ 样本不足({len(df)}条)")
            return
        X = df[['ret', 'range', 'vol_ratio']]
        y = df['y']
        self.lr.fit(X, y)
        self.rf.fit(X, y)
        self.sltp_model.train(df, tp_threshold=0.002, sl_threshold=0.002)
        self.trained = True
        self.logger.info(f"✅ 模型训练完成 | 上涨概率:{y.mean():.2%}")

    # 交易信号计算
    def signal(self, df):
        if not self.trained or df.empty or len(df) < 20:
            return 0
        try:
            latest = df.iloc[-1]
            vol_mean = df['vol'].rolling(20).mean().iloc[-1]
            ret = (latest['close'] - latest['open']) / latest['open'] if latest['open'] != 0 else 0
            range_val = (latest['high'] - latest['low']) / latest['open'] if latest['open'] != 0 else 0
            vol_ratio = latest['vol'] / vol_mean if vol_mean > 0 else 1.0
            x = pd.DataFrame([{'ret': ret, 'range': range_val, 'vol_ratio': vol_ratio}])
            lr_prob = self.lr.predict_proba(x)[0][1]
            rf_prob = self.rf.predict_proba(x)[0][1]
            weighted_prob = lr_prob * self.lr_weight + rf_prob * self.rf_weight
            self.logger.info(f"📊 信号 | LR:{lr_prob:.2%} | RF:{rf_prob:.2%} | 加权:{weighted_prob:.2%}")
            return 1 if weighted_prob >= self.vote_threshold else 0
        except Exception as e:
            self.logger.error(f"信号计算失败: {str(e)[:100]}")
            return 0

    # 收益风险比计算
    def calculate_profit_risk_ratio(self, df):
        if df.empty or len(df) < 10:
            return 0, 0
        recent_df = df.iloc[-10:]
        avg_range = (recent_df['high'] - recent_df['low']).mean() / recent_df['close'].mean()
        potential_profit = self.target_profit_ratio
        potential_risk = avg_range / 2
        profit_risk_ratio = potential_profit / potential_risk if potential_risk > 0 else 0
        return profit_risk_ratio, potential_profit

    # 开仓前止盈止损预校验
    def check_pre_open_sltp(self, df):
        if not self.trained or df.empty:
            return True
        pre_entry_price = self.get_realtime_price() or df['close'].iloc[-1]
        tp_prob, sl_prob = self.sltp_model.predict(df, entry_price=pre_entry_price, debug=True)
        prob_check = tp_prob >= self.tp_prob_threshold or sl_prob >= self.sl_prob_threshold
        profit_risk_ratio, potential_profit = self.calculate_profit_risk_ratio(df)
        profit_check = (profit_risk_ratio >= self.min_profit_risk_ratio) and (
                    potential_profit >= self.target_profit_ratio)
        self.logger.info(
            f"📊 开仓检查 | TP概率:{tp_prob:.2%} | SL概率:{sl_prob:.2%} | 收益风险比:{profit_risk_ratio:.2f}")
        return prob_check and profit_check

    # 止盈止损+布林下轨平仓
    def check_stop_loss_take_profit(self, df):
        if self.position != 1 or self.entry_price is None:
            return
        realtime_price = self.get_realtime_price()
        if realtime_price <= 0:
            self.logger.warning("⚠️ 实时价无效，跳过止盈止损")
            return

        # 布林下轨跌破强制平仓（最高优先级）
        if self.boll_lower > 0 and realtime_price < self.boll_lower:
            self.logger.info(f"🛑 跌破布林下轨强制平仓 | 当前价:{realtime_price:.2f} < 下轨:{self.boll_lower:.2f}")
            self.sell(is_force=True)
            return

        profit_ratio = (realtime_price - self.entry_price) / self.entry_price
        profit_abs = (realtime_price - self.entry_price) * self.hold_amount
        profit_status = "盈利" if profit_ratio > 0 else "亏损" if profit_ratio < 0 else "持平"
        tp_prob, sl_prob = self.sltp_model.predict(df, entry_price=self.entry_price, debug=True)

        tp_conditions = [
            profit_ratio >= self.min_profit_threshold,
            profit_ratio >= self.target_profit_ratio,
            tp_prob >= self.tp_prob_threshold
        ]
        sl_conditions = [
            profit_ratio <= -self.min_loss_threshold,
            sl_prob >= self.sl_prob_threshold
        ]
        self.logger.info(f"📊 盈亏状态 | {profit_status} {profit_ratio:.2%} | 盈亏金额: {profit_abs:.2f} USDT")
        if all(tp_conditions):
            self.logger.info(f"🚀 触发止盈 | 盈利{profit_ratio:.2%} ≥ 目标{self.target_profit_ratio * 100}%")
            self.sell(is_force=True)
        elif all(sl_conditions):
            self.logger.info(f"🛑 触发止损 | 亏损{abs(profit_ratio):.2%} ≥ {self.min_loss_threshold * 100}%")
            self.sell(is_force=True)

    # 布林带过滤（从配置读取参数）
    def boll_filter(self):
        try:
            df = self.fetch_ohlcv('1d', 50)
            if df.empty:
                self.trade_allowed = True
                return
            bb = ta.volatility.BollingerBands(df['close'], window=self.boll_window, window_dev=self.boll_dev)
            boll_low = bb.bollinger_lband().iloc[-1]
            self.boll_lower = boll_low
            current_price = self.get_realtime_price()
            self.trade_allowed = current_price > boll_low
            status = "✅ 允许交易" if self.trade_allowed else "⚠️ 禁止交易（跌破布林下轨）"
            self.logger.info(f"{status} | 当前价:{current_price:.2f} | 布林下轨:{boll_low:.2f}")
        except Exception as e:
            self.logger.error(f"布林带过滤失败: {str(e)[:100]}")
            self.trade_allowed = True

    # 持仓查询（CCXT+原生API双重兜底）
    def check_position(self):
        try:
            # 优先CCXT查询
            balance = self.client.okx_ccxt.fetch_balance({"type": "margin"})
            base_coin = self.symbol.split('-')[0]
            free = balance['free'].get(base_coin, 0)
            used = balance['used'].get(base_coin, 0)
            hold_amount = float(free) + float(used)

            if hold_amount > 0.000001:
                self.position = 1
                self.entry_price = self.entry_price or self.get_realtime_price()
                self.hold_amount = hold_amount
                self.logger.info(f"✅ 当前现货持仓 | {self.hold_amount:.6f} {base_coin} | 开仓价:{self.entry_price:.2f}")
            else:
                self.position = 0
                self.entry_price = None
                self.hold_amount = 0
                self.logger.info("✅ 当前无现货持仓")
        except Exception as e:
            # 备用原生API查询
            try:
                params = {
                    "instId": self.symbol,
                    "instType": "SPOT",
                    "mgnMode": "cross"
                }
                result = self.client.request("GET", "/api/v5/account/positions", params=params)
                if result and len(result) > 0:
                    pos = result[0]
                    hold_amount = float(pos['pos'])
                    if hold_amount > 0:
                        self.position = 1
                        self.entry_price = float(pos['avgPx'])
                        self.hold_amount = hold_amount
                        self.logger.info(f"✅ 当前现货持仓 | {self.hold_amount:.6f} | 开仓价:{self.entry_price:.2f}")
                    else:
                        self.position = 0
                        self.entry_price = None
                        self.hold_amount = 0
                else:
                    self.logger.info("✅ 当前无现货持仓")
            except Exception as e2:
                self.logger.warning(f"⚠️ 持仓查询失败，使用本地记录: {str(e2)[:50]}")
                pass

    # 现货买入（装饰器日志）
    @trade_logger
    def buy(self):
        if self.position != 0:
            self.logger.warning("⚠️ 当前已有现货持仓，无法买入")
            return None
        realtime_price = self.get_realtime_price()
        if realtime_price <= 0:
            self.logger.error("❌ 实时价无效，无法买入")
            return None
        order_amount = self.calculate_order_amount(realtime_price)
        if order_amount <= 0:
            return None
        try:
            data = {
                "instId": self.symbol,
                "instType": "SPOT",
                "tdMode": "cross",
                "side": "buy",
                "ordType": "market",
                "sz": str(order_amount)
            }
            result = self.client.request("POST", "/api/v5/trade/order", data=data)
            if result and len(result) > 0:
                order = result[0]
                self.position = 1
                self.entry_price = float(order.get('avgPx', realtime_price))
                self.hold_amount = order_amount
                self.logger.info(
                    f"🟢 现货买入成功 | 订单ID:{order['ordId']} | 均价:{self.entry_price:.2f} | 数量:{order_amount}")
                # 保存交易记录
                trade_record = {
                    "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "type": "现货买入",
                    "price": self.entry_price,
                    "size": order_amount,
                    "profit": 0.0,
                    "order_id": order['ordId']
                }
                save_trade_record(trade_record)
                return order
            else:
                self.logger.error("❌ 现货买入失败")
                return None
        except Exception as e:
            self.logger.error(f"现货买入异常: {str(e)[:100]}")
            return None

    # 现货卖出（装饰器日志）
    @trade_logger
    def sell(self, is_force=False):
        if not is_force and self.position != 1:
            self.logger.warning("⚠️ 当前无现货持仓，无法卖出")
            return None
        realtime_price = self.get_realtime_price()
        if realtime_price <= 0:
            self.logger.error("❌ 实时价无效，无法卖出")
            return None
        order_amount = self.hold_amount if self.hold_amount > 0 else self.calculate_order_amount(realtime_price)
        try:
            data = {
                "instId": self.symbol,
                "instType": "SPOT",
                "tdMode": "cross",
                "side": "sell",
                "ordType": "market",
                "sz": str(order_amount)
            }
            result = self.client.request("POST", "/api/v5/trade/order", data=data)
            if result and len(result) > 0:
                order = result[0]
                sell_price = float(order.get('avgPx', realtime_price))
                profit = (sell_price - self.entry_price) * order_amount if self.entry_price else 0.0
                self.position = 0
                self.entry_price = None
                self.hold_amount = 0
                self.logger.info(
                    f"🔴 现货卖出成功 | 订单ID:{order['ordId']} | 均价:{sell_price:.2f} | 盈亏:{profit:.2f} USDT")
                # 保存交易记录
                trade_record = {
                    "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "type": "现货卖出",
                    "price": sell_price,
                    "size": order_amount,
                    "profit": profit,
                    "order_id": order['ordId']
                }
                save_trade_record(trade_record)
                return order
            else:
                self.logger.error("❌ 现货卖出失败")
                return None
        except Exception as e:
            self.logger.error(f"现货卖出异常: {str(e)[:100]}")
            return None

    # 强制平仓
    def force_close_position(self):
        self.logger.info("\n🔴 执行现货强制平仓...")
        max_retry = 3
        retry_count = 0
        while retry_count < max_retry and self.position == 1:
            self.logger.info(f"📌 平仓重试 {retry_count + 1}/{max_retry}")
            result = self.sell(is_force=True)
            if result:
                self.logger.info("✅ 现货强制平仓成功")
                break
            retry_count += 1
            time.sleep(2)
        if self.position == 1:
            self.logger.error("❌ 现货强制平仓失败，请手动操作")

    # 策略主运行逻辑
    def run_strategy(self):
        self.logger.info(f"{'=' * 60}")
        self.logger.info(f"📈 OKX现货杠杆模拟盘策略启动 | {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info(f"{'=' * 60}\n")
        # 初始化
        self.client.set_leverage(self.symbol, self.leverage)
        self.check_position()
        df_init = self.fetch_ohlcv('1h', 500)
        self.train(df_init)
        cycle = 1
        total_trades = 0
        try:
            while True:
                try:
                    self.logger.info(f"\n{'-' * 40} 第{cycle}轮循环 {'-' * 40}")
                    self.get_realtime_price()
                    df = self.fetch_ohlcv('1h', 300)
                    self.boll_filter()
                    self.check_position()
                    # 定期重训
                    if cycle % 24 == 0 and not df.empty:
                        self.logger.info("🔄 定期重训模型...")
                        self.train(df)
                    # 交易信号
                    signal = self.signal(df)
                    self.logger.info(f"📊 交易信号:{'📈 买入' if signal == 1 else '📉 观望'} | 持仓:{self.position}")
                    # 执行交易
                    trade_executed = False
                    if self.trade_allowed:
                        if signal == 1 and self.position == 0:
                            if self.check_pre_open_sltp(df):
                                result = self.buy()
                                trade_executed = result is not None
                            else:
                                self.logger.info("📉 开仓检查不达标，放弃买入")
                        if self.position == 1 and not df.empty:
                            self.check_stop_loss_take_profit(df)
                    if trade_executed:
                        total_trades += 1
                    self.logger.info(f"📋 运行统计 | 总交易次数:{total_trades}")
                    cycle += 1
                    self.logger.info(f"⏳ 等待{self.cycle_interval}秒...")
                    time.sleep(self.cycle_interval)
                except Exception as e:
                    self.logger.error(f"循环异常: {str(e)[:80]}")
                    time.sleep(30)
        except KeyboardInterrupt:
            self.logger.info("\n🛑 用户终止程序")
            if self.position == 1:
                self.force_close_position()
            # 输出交易统计报告
            self.logger.info(f"\n{'=' * 50} 交易统计报告 {'=' * 50}")
            stats = get_trade_statistics()
            if not stats.empty:
                self.logger.info(f"\n{stats.to_string(index=False)}")
            else:
                self.logger.info("📊 暂无交易记录")
            self.logger.info(
                f"📋 策略结束 | 总交易次数:{total_trades} | 时间:{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            self.logger.info(f"{'=' * 100}")


