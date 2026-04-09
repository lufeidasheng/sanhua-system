import logging
import os

def validate_and_fix(base_path):
    logging.info("开始校验配置项...")

    config_path = os.path.join(base_path, "config.py")
    if not os.path.isfile(config_path):
        logging.error(f"配置文件不存在: {config_path}")
        # 可以考虑创建默认配置
        with open(config_path, "w") as f:
            f.write("# 默认配置文件\n")
            f.write("REPLY_THREAD_POOL_SIZE = 4\n")  # 加入缺失配置示例
        logging.info(f"已创建默认配置文件: {config_path}")
    else:
        # 简单示例：检查是否包含关键配置
        with open(config_path, "r") as f:
            content = f.read()
        if "REPLY_THREAD_POOL_SIZE" not in content:
            logging.warning("配置文件缺少 REPLY_THREAD_POOL_SIZE，添加默认值。")
            with open(config_path, "a") as f:
                f.write("\nREPLY_THREAD_POOL_SIZE = 4\n")
        else:
            logging.info("配置文件已包含 REPLY_THREAD_POOL_SIZE。")

    logging.info("配置校验完成。")
