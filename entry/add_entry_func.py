import os

path = "modules/cli_entry/cli_main.py"

with open(path, "r+", encoding="utf-8") as f:
    content = f.read()
    if "def entry" not in content:
        f.write("\n\ndef entry():\n    print('默认 CLI 入口函数')\n")
        print(f"✅ 添加 entry 函数：{path}")
    else:
        print(f"ℹ️ 已存在 entry 函数：{path}")

