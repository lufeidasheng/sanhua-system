import os
import re

cli_entry_path = "entry/cli_entry/cli_entry.py"

# 1. 插入 sys.path 修复代码
def fix_sys_path():
    with open(cli_entry_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    insert_code = (
        "import sys\n"
        "import os\n"
        "sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))\n"
    )

    # 如果已存在则跳过
    already_fixed = any("sys.path.append" in line for line in lines)
    if not already_fixed:
        # 找到第一个非注释行，插入代码
        for i, line in enumerate(lines):
            if line.strip() and not line.strip().startswith("#"):
                lines.insert(i, insert_code + "\n")
                break

        with open(cli_entry_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        print(f"✅ 修复 sys.path 成功")
    else:
        print(f"✅ sys.path 已存在，无需重复修复")


# 2. 修复 ReplyDispatcher 初始化错误
def fix_reply_dispatcher():
    with open(cli_entry_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 匹配类似 ReplyDispatcher(... config=xxx ...)
    pattern = r"ReplyDispatcher\s*\((.*?)\)"
    
    def replacer(match):
        args = match.group(1)
        # 去掉 config=... 部分
        new_args = re.sub(r"\bconfig\s*=\s*[^,)\n]+,?", "", args)
        new_args = re.sub(r",\s*\)", ")", new_args + ")")  # 修复逗号末尾
        return f"ReplyDispatcher({new_args.strip()})"

    new_content = re.sub(pattern, replacer, content)

    if content != new_content:
        with open(cli_entry_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print("✅ 修复 ReplyDispatcher 初始化参数成功")
    else:
        print("✅ ReplyDispatcher 已无 config 参数，无需修复")


# 执行修复
fix_sys_path()
fix_reply_dispatcher()
