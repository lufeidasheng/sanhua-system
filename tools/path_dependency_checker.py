import os
import logging

def check_paths(base_path):
    logging.info("开始检测关键路径依赖...")

    # 你可以定义需要检查的关键目录和文件
    key_paths = [
        os.path.join(base_path, "core"),
        os.path.join(base_path, "entry"),
        os.path.join(base_path, "modules"),
    ]

    for path in key_paths:
        if not os.path.exists(path):
            logging.error(f"关键路径不存在: {path}")
        else:
            logging.info(f"路径存在：{path}")

    logging.info("路径依赖检测完成。")
