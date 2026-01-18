import logging
import os
from datetime import datetime


def init_logger(log_path, log_level="INFO"):
    """
    初始化日志系统
    :param log_path: 日志保存目录
    :param log_level: 日志级别（DEBUG/INFO/WARNING/ERROR）
    :return: logger实例
    """
    # 创建日志目录
    if not os.path.exists(log_path):
        os.makedirs(log_path)

    # 日志文件名：按日期生成
    log_filename = f"okx_strategy_{datetime.now().strftime('%Y%m%d')}.log"
    log_filepath = os.path.join(log_path, log_filename)

    # 定义日志格式
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")

    # 创建logger
    logger = logging.getLogger("OKXQuantStrategy")
    logger.setLevel(log_level)
    logger.handlers.clear()  # 避免重复添加处理器

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件处理器
    file_handler = logging.FileHandler(log_filepath, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


# 测试日志（可选）
if __name__ == "__main__":
    logger = init_logger("./logs")
    logger.info("测试信息日志")
    logger.warning("测试警告日志")
    logger.error("测试错误日志")
    print("✅ 日志测试完成，查看 ./logs 目录下的日志文件")