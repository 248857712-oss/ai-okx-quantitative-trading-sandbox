import ccxt
import pandas as pd
import time
from datetime import datetime

# ===================== 核心修改：配置代理参数 =====================

# 选项1：SOCKS5代理（最常用，如Clash/V2Ray本地代理，默认端口7890）
PROXIES = {
    "http": "http://127.0.0.1:10808",
    "https": "http://127.0.0.1:10808"
}


# ===================== 配置参数（无需修改） =====================
EXCHANGE_NAME = "binance"
SYMBOL = "BTC/USDT"
TIMEFRAME = "1h"
TARGET_COUNT = 4000
OUTPUT_FILE = "C:\\Users\\neverleave\\Desktop\\量化策略\\btc_1h_4000.csv"

# ===================== 核心下载逻辑（已集成代理） =====================
def download_4000_1h_klines():
    # 初始化交易所（添加代理配置）
    exchange = ccxt.binance({
        'enableRateLimit': True,  # 自动遵守API频率限制
        'timeout': 30000,
        'proxies': PROXIES        # 核心：启用代理
    })

    # 计算起始时间：从当前时间往前推4000小时（确保能拿到足够数据）
    end_timestamp = exchange.milliseconds()
    start_timestamp = end_timestamp - (TARGET_COUNT + 100) * 3600 * 1000  # 多取100条备用

    all_klines = []
    current_timestamp = start_timestamp

    print(f"📥 开始下载{SYMBOL} {TIMEFRAME} K线数据（目标4000条）...")
    print(f"⏰ 时间范围：从 {datetime.fromtimestamp(current_timestamp/1000)} 开始")

    # 分页下载（Binance单次最多返回1000条，需循环）
    while len(all_klines) < TARGET_COUNT and current_timestamp < end_timestamp:
        try:
            # 单次下载1000条
            klines = exchange.fetch_ohlcv(
                symbol=SYMBOL,
                timeframe=TIMEFRAME,
                since=current_timestamp,
                limit=1000
            )
            if not klines:
                break

            all_klines.extend(klines)
            # 更新下一页起始时间（最后一条数据的时间 + 1小时）
            current_timestamp = klines[-1][0] + 3600 * 1000
            # 打印进度
            print(f"✅ 已下载 {len(all_klines)} 条，当前时间：{datetime.fromtimestamp(current_timestamp/1000)}")
            time.sleep(1)  # 避免触发频率限制

        except Exception as e:
            print(f"⚠️  下载出错：{e}")
            break

    # 截取前4000条数据（确保数量精准）
    all_klines = all_klines[:TARGET_COUNT]
    if len(all_klines) < TARGET_COUNT:
        print(f"⚠️  仅下载到 {len(all_klines)} 条数据（不足4000条），请检查网络或重试")
    else:
        print(f"✅ 成功下载 {len(all_klines)} 条1H K线数据！")

    # ===================== 格式处理（适配回测脚本） =====================
    # 转换为DataFrame
    df = pd.DataFrame(all_klines, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
    # 1. 时间戳转正常时间格式
    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
    # 2. 数值类型转换（确保价格为浮点数）
    for col in ['open', 'high', 'low', 'close', 'vol']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    # 3. 删除空值（若有）
    df = df.dropna(subset=['open', 'close'])
    # 4. 按时间升序排序 + 保留序号列
    df = df.sort_values('ts').reset_index(drop=False)

    # ===================== 保存为CSV（带序号） =====================
    df.to_csv(OUTPUT_FILE, index=False, encoding='utf-8')
    print(f"💾 数据已保存至：{OUTPUT_FILE}")
    print("\n📄 数据预览（前3行）：")
    print(df.head(3))
    print(f"\n⏰ 数据时间范围：{df['ts'].min()} ~ {df['ts'].max()}")
    print(f"📊 最终数据条数：{len(df)} 条")

if __name__ == "__main__":
    # 安装依赖（若未安装）
    try:
        import ccxt
    except ImportError:
        print("📦 正在安装ccxt依赖...")
        import subprocess
        subprocess.check_call(["pip", "install", "ccxt", "pandas"])
        # 若使用SOCKS5代理，自动安装pysocks依赖
        subprocess.check_call(["pip", "install", "pysocks"])
        print("✅ 依赖安装完成（含SOCKS5代理依赖）！")
        import ccxt

    # 执行下载
    download_4000_1h_klines()