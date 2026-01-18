import json
import os


def load_config(config_path="./config.json"):
    """
    加载配置文件
    :param config_path: 配置文件路径
    :return: 配置字典
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # 简单校验必要字段
    required_fields = ["okx", "proxy", "strategy", "log"]
    for field in required_fields:
        if field not in config:
            raise ValueError(f"配置文件缺少必要字段: {field}")

    return config


# 测试配置加载（可选）
if __name__ == "__main__":
    try:
        config = load_config()
        print("✅ 配置加载成功！")
        print(f"交易对: {config['okx']['symbol']}")
        print(f"仓位比例: {config['strategy']['position_ratio'] * 100}%")
    except Exception as e:
        print(f"❌ 配置加载失败: {e}")