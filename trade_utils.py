import pandas as pd
import os
from datetime import datetime


def save_trade_record(record, csv_path="./trades.csv"):
    """
    保存交易记录到CSV文件
    :param record: 交易记录字典，格式如下
    {
        "time": "2026-01-18 12:00:00",
        "type": "开多/平仓",
        "price": 45000.0,
        "size": 0.02,
        "profit": 100.0,
        "order_id": "123456"
    }
    :param csv_path: CSV文件路径
    """
    # 确保record字段完整
    required_fields = ["time", "type", "price", "size", "profit", "order_id"]
    for field in required_fields:
        if field not in record:
            raise ValueError(f"交易记录缺少字段: {field}")

    # 转为DataFrame
    df_new = pd.DataFrame([record])

    # 如果文件不存在，创建并写入表头；如果存在，追加数据
    if not os.path.exists(csv_path):
        df_new.to_csv(csv_path, index=False, encoding="utf-8")
    else:
        df_new.to_csv(csv_path, index=False, encoding="utf-8", mode="a", header=False)


def load_trade_records(csv_path="./trades.csv"):
    """
    加载交易记录
    :param csv_path: CSV文件路径
    :return: 交易记录DataFrame
    """
    if not os.path.exists(csv_path):
        return pd.DataFrame(columns=["time", "type", "price", "size", "profit", "order_id"])
    return pd.read_csv(csv_path, encoding="utf-8")


# 测试代码
if __name__ == "__main__":
    test_record = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": "开多",
        "price": 45000.0,
        "size": 0.02,
        "profit": 0.0,
        "order_id": "TEST123456"
    }
    save_trade_record(test_record)
    df = load_trade_records()
    print("✅ 测试交易记录已保存：")
    print(df)