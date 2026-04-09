import os, shutil, sys

# ------------ 配置区 ------------
OLD_CORE = "core"               # 旧版核心目录
EXTRA_FILES = ["main.py", "run.py", "aicore-main.py", "jaoshoujia-main.py"]
# --------------------------------

def rmdir(path):
    if os.path.exists(path):
        shutil.rmtree(path)
        print(f"🗑️ 删除目录: {path}")

def rmfile(path):
    if os.path.isfile(path):
        os.remove(path)
        print(f"🗑️ 删除文件: {path}")

def clear_pycache(root="."):
    for rt, dirs, _ in os.walk(root):
        for d in dirs:
            if d == "__pycache__":
                rmdir(os.path.join(rt, d))

if __name__ == "__main__":
    rmdir(OLD_CORE)
    clear_pycache()

    for f in EXTRA_FILES:
        rmfile(f)

    print("✅ 历史内容清理完成")
