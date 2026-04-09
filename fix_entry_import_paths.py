import os

# 需要插入的导入修复代码
IMPORT_FIX = '''\
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
'''

# 要扫描的入口目录
ENTRY_DIR = "entry"

# 需要修复的入口文件名（也可以改成全自动遍历所有 .py）
TARGET_FILES = [
    "cli_entry.py",
    "gui_entry.py",
    "voice_entry.py",
]

def needs_fix(content):
    return "sys.path.insert" not in content and "core.core2_0" in content

def fix_entry_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    if needs_fix(content):
        print(f"正在修复: {filepath}")
        new_content = IMPORT_FIX + "\n" + content
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
    else:
        print(f"无需修复: {filepath}")

def main():
    for root, dirs, files in os.walk(ENTRY_DIR):
        for file in files:
            if file in TARGET_FILES and file.endswith(".py"):
                filepath = os.path.join(root, file)
                fix_entry_file(filepath)

if __name__ == "__main__":
    main()
