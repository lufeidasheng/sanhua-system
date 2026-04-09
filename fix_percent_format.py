import os
import re

MODULE_ROOT = "modules"

def fix_format_string(content: str) -> str:
    """将 log.info("... %% __name__") 替换为 f-string 格式"""
    content = re.sub(
        r'log\.info\("([^"]*?)%%s([^"]*?)"\s*%%\s*__name__\)',
        r'log.info(f"\1{__name__}\2")',
        content,
    )
    content = re.sub(
        r'print\("([^"]*?)%%s([^"]*?)"\s*%%\s*__name__\)',
        r'print(f"\1{__name__}\2")',
        content,
    )
    # 替换仍可能存在的 %% 为 %
    content = content.replace("%%", "%")
    return content

def scan_and_fix():
    count = 0
    for root, _, files in os.walk(MODULE_ROOT):
        if "module.py" in files:
            path = os.path.join(root, "module.py")
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            new_content = fix_format_string(content)
            if new_content != content:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                print(f"✅ 修复: {path}")
                count += 1
    print(f"\n🛠️ 总共修复 {count} 个模块")

if __name__ == "__main__":
    scan_and_fix()
