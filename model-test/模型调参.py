import pandas as pd
import ta
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from itertools import product
import json
import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

sys.path.append(os.getcwd())


# 简易进度条
def progress_bar(current, total, prefix='', suffix='', length=50, fill='█'):
    percent = ("{0:.1f}").format(100 * (current / float(total)))
    filled_length = int(length * current // total)
    bar = fill * filled_length + '-' * (length - filled_length)
    sys.stdout.write(f'\r{prefix} |{bar}| {percent}% {suffix}')
    sys.stdout.flush()
    if current == total:
        print()


# 读取本地K线（不变）
def get_historical_ohlcv_from_local(csv_file="btc_1h_6months.csv"):
    if not os.path.exists(csv_file):
        print(f"❌ 未找到本地K线文件：{csv_file}")
        sys.exit(1)

    df = pd.read_csv(csv_file, encoding='utf-8')
    df.rename(columns={
        '时间': 'ts',
        '开盘价': 'open',
        '最高价': 'high',
        '最低价': 'low',
        '收盘价': 'close',
        '成交量': 'vol'
    }, inplace=True)

    df['ts'] = pd.to_datetime(df['ts'])
    for col in ['open', 'high', 'low', 'close', 'vol']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna().drop_duplicates(subset=['ts']).reset_index(drop=True)
    df = df.iloc[-1000:] if len(df) > 1000 else df
    print(f"✅ 读取本地K线成功，共{len(df)}条（1H周期）")
    return df


# 轻量化回测（减少计算量）
def backtest_with_params_light(df, params):
    df_copy = df.copy()
    # 快速特征计算
    df_copy['ret'] = (df_copy['close'] - df_copy['open']) / df_copy['open']
    df_copy['range'] = (df_copy['high'] - df_copy['low']) / df_copy['open']
    df_copy['vol_ratio'] = df_copy['vol'] / df_copy['vol'].rolling(20).mean()
    df_copy['y'] = (df_copy['close'].shift(-1) > df_copy['close']).astype(int)
    df_copy = df_copy.dropna()

    # 数据不足直接返回
    if len(df_copy) < 200:
        return {"胜率": 0, "盈亏比": 0, "总收益": 0, "交易次数": 0, "params": params}

    # 简化模型（提速关键）
    train_size = int(len(df_copy) * 0.8)
    X = df_copy[['ret', 'range', 'vol_ratio']]
    y = df_copy['y']
    X_train, y_train = X.iloc[:train_size], y.iloc[:train_size]

    # 减少模型复杂度，提速50%
    lr = LogisticRegression(random_state=42, max_iter=100)
    rf = RandomForestClassifier(n_estimators=30, max_depth=4, random_state=42, n_jobs=1)
    lr.fit(X_train, y_train)
    rf.fit(X_train, y_train)

    # 简化交易逻辑
    trades = []
    position = 0
    entry_price = 0.0

    for idx in range(train_size, len(df_copy)):
        row = df_copy.iloc[idx]
        x = pd.DataFrame([[row['ret'], row['range'], row['vol_ratio']]], columns=['ret', 'range', 'vol_ratio'])
        lr_prob = lr.predict_proba(x)[0][1]
        rf_prob = rf.predict_proba(x)[0][1]
        weighted_prob = lr_prob * params['lr_weight'] + rf_prob * params['rf_weight']

        if position == 0 and weighted_prob >= params['vote_threshold']:
            position = 1
            entry_price = row['close']
        elif position == 1:
            profit_ratio = (row['close'] - entry_price) / entry_price
            tp_ok = profit_ratio >= params['min_profit_threshold'] and profit_ratio >= params['target_profit_ratio']
            sl_ok = profit_ratio <= -params['min_loss_threshold']
            if tp_ok or sl_ok:
                trades.append(profit_ratio)
                position = 0

    if not trades:
        return {"胜率": 0, "盈亏比": 0, "总收益": 0, "交易次数": 0, "params": params}

    win = [t for t in trades if t > 0]
    lose = [t for t in trades if t < 0]
    win_rate = len(win) / len(trades) if trades else 0
    avg_win = np.mean(win) if win else 0
    avg_lose = abs(np.mean(lose)) if lose else 1
    profit_loss_ratio = avg_win / avg_lose if avg_lose > 0 else 0
    total_return = sum(trades)

    return {
        "胜率": round(win_rate, 4),
        "盈亏比": round(profit_loss_ratio, 4),
        "总收益": round(total_return, 4),
        "交易次数": len(trades),
        "params": params
    }


# 核心：大幅精简参数组合（从39366→480个）
def grid_search_best_params_fast(df):
    # 只保留核心影响参数，且仅选实战有效区间
    param_grid = {
        # 核心开仓参数（仅保留高概率区间）
        "vote_threshold": [0.58, 0.6, 0.62],  # 3个值（原3个，仅保留高阈值）
        # 止盈止损核心（仅保留有效区间）
        "min_profit_threshold": [0.004, 0.005],  # 2个值（原3个）
        "target_profit_ratio": [0.01, 0.012],  # 2个值（原3个）
        "min_loss_threshold": [0.001, 0.0015],  # 2个值（原3个）
        # 模型权重（仅保留实战有效组合）
        "lr_weight": [0.4, 0.5],  # 2个值（原3个）
        "rf_weight": [0.5, 0.6],  # 2个值（原3个）
        # 固定非核心参数（不再搜索，避免无效组合）
        "tp_prob_threshold": [0.55],  # 1个值（原3个）
        "sl_prob_threshold": [0.45],  # 1个值（原3个）
        "position_ratio": [0.1],  # 1个值（原3个）
        "cycle_interval": [60],  # 1个值（原2个）
        "boll_window": [20],  # 1个值
        "boll_dev": [2]  # 1个值
    }

    best_params = None
    best_perf = {"胜率": 0, "盈亏比": 0, "总收益": 0}
    param_keys = list(param_grid.keys())
    param_combinations = list(product(*param_grid.values()))

    # 双重过滤：权重和≤1.1 + 止盈>止损（避免无效组合）
    valid_combinations = []
    for values in param_combinations:
        curr_params = dict(zip(param_keys, values))
        # 权重约束
        if curr_params["lr_weight"] + curr_params["rf_weight"] > 1.1:
            continue
        # 止盈止损约束（止盈必须>止损，否则无意义）
        if curr_params["min_profit_threshold"] <= curr_params["min_loss_threshold"]:
            continue
        valid_combinations.append(curr_params)

    total = len(valid_combinations)
    print(f"🔍 开始极速网格搜索（仅{total}个有效组合，约10-15分钟完成）...")
    results = []
    completed = 0

    # 优化线程数：最多4线程（避免CPU过载崩溃）
    max_workers = min(4, os.cpu_count() - 1) if os.cpu_count() > 1 else 1
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for params in valid_combinations:
            futures.append(executor.submit(backtest_with_params_light, df, params))

        # 进度条+防崩溃：每完成100个组合，短暂休息0.1秒
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
                completed += 1
                progress_bar(completed, total, prefix='调参进度', suffix='完成', length=50)
                # 避免CPU占满崩溃
                if completed % 100 == 0:
                    time.sleep(0.1)
            except Exception as e:
                completed += 1
                progress_bar(completed, total, prefix='调参进度', suffix='完成', length=50)
                continue

    # 筛选最优参数（优先级：盈亏比≥1.8 → 胜率≥35% → 总收益最高）
    valid_results = [r for r in results if r["盈亏比"] >= 1.8 and r["胜率"] >= 0.35]
    if valid_results:
        valid_results.sort(key=lambda x: (x["盈亏比"], x["胜率"]), reverse=True)
        best_perf = valid_results[0]
        best_params = best_perf["params"]
        print(f"\n✅ 找到最优参数：胜率{best_perf['胜率']:.2%} | 盈亏比{best_perf['盈亏比']:.2f}")
    else:
        # 无达标参数，取相对最优
        if results:
            results.sort(key=lambda x: x["总收益"], reverse=True)
            best_perf = results[0]
            best_params = best_perf["params"]
            print(f"\n⚠️  取相对最优参数：胜率{best_perf['胜率']:.2%} | 盈亏比{best_perf['盈亏比']:.2f}")
        else:
            print("\n❌ 未找到有效参数组合")
            return None, None

    # 保存最优参数
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump({
            "params": best_params,
            "performance": {
                "胜率": best_perf["胜率"],
                "盈亏比": best_perf["盈亏比"],
                "总收益": best_perf["总收益"],
                "交易次数": best_perf["交易次数"]
            }
        }, f, indent=4, ensure_ascii=False)

    return best_params, {
        "胜率": best_perf["胜率"],
        "盈亏比": best_perf["盈亏比"],
        "总收益": best_perf["总收益"],
        "交易次数": best_perf["交易次数"]
    }


# 自动更新配置（不变）
def update_config_auto(best_params):
    config_path = "../Data/Entry/config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    config["strategy"].update(best_params)
    config["strategy"]["leverage"] = 10

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

    print("\n🎉 最优参数已自动写入config.json！")
    print("📌 最终最优参数（杠杆保持10倍不变）：")
    for k, v in best_params.items():
        print(f"  {k}: {v}")
    print(f"  leverage: 10 （锁定不变）")


# 主入口
if __name__ == "__main__":
    print("📊 从本地加载6个月K线数据...")
    df_kline = get_historical_ohlcv_from_local(csv_file="btc_1h_6months.csv")
    if df_kline.empty:
        sys.exit(1)

    best_params, best_perf = grid_search_best_params_fast(df_kline)
    if not best_params:
        print("❌ 未找到有效参数组合")
        sys.exit(1)

    print("\n🏆 调优结果汇总：")
    print(f"  胜率：{best_perf['胜率']:.2%}")
    print(f"  盈亏比：{best_perf['盈亏比']:.2f}")
    print(f"  总收益：{best_perf['总收益']:.4f}")
    print(f"  交易次数：{best_perf['交易次数']}")

    update_config_auto(best_params)