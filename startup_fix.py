import os
import sys

CONFIG_PATH = 'core/core.core2_0/config.py'
CERTS_DIR = 'core/core.core2_0/certs'

def ensure_config_attribute():
    if not os.path.exists(CONFIG_PATH):
        print(f"❌ 找不到配置文件: {CONFIG_PATH}")
        return

    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    has_attr = any("REPLY_THREAD_POOL_SIZE" in line for line in lines)
    if not has_attr:
        with open(CONFIG_PATH, 'a', encoding='utf-8') as f:
            f.write("\nREPLY_THREAD_POOL_SIZE = 4  # 默认线程池大小\n")
        print("✅ 已自动添加 REPLY_THREAD_POOL_SIZE = 4 到 config.py")
    else:
        print("✅ config.py 中已包含 REPLY_THREAD_POOL_SIZE")

def ensure_certs_folder():
    if not os.path.exists(CERTS_DIR):
        os.makedirs(CERTS_DIR)
        print(f"✅ 已创建证书目录: {CERTS_DIR}")
    else:
        print(f"✅ 证书目录已存在: {CERTS_DIR}")

if __name__ == '__main__':
    ensure_config_attribute()
    ensure_certs_folder()
