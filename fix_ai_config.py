# fix_ai_config.py
import os

aicore_init_path = "core/core.core2_0/aicore/__init__.py"
config_path = "core/core.core2_0/config.py"

# 修复 __init__.py 导入 AICore
if os.path.exists(aicore_init_path):
    with open(aicore_init_path, "r+", encoding="utf-8") as f:
        content = f.read()
        if "AICore" not in content:
            f.seek(0)
            f.write("from .aicore import AICore\n" + content)
            print("✅ 已添加 AICore 导入到 __init__.py")
        else:
            print("✅ 已存在 AICore 导入")

# 添加 REPLY_THREAD_POOL_SIZE 配置
if os.path.exists(config_path):
    with open(config_path, "r+", encoding="utf-8") as f:
        content = f.read()
        if "REPLY_THREAD_POOL_SIZE" not in content:
            f.write("\n# 回复调度器线程池大小\nREPLY_THREAD_POOL_SIZE = 4\n")
            print("✅ 已添加 REPLY_THREAD_POOL_SIZE 到 config.py")
        else:
            print("✅ config.py 中已存在 REPLY_THREAD_POOL_SIZE")
else:
    print("❌ 未找到 config.py 文件")
