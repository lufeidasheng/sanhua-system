import os
import re

PROJECT_DIR = "/home/lufei/文档/聚核助手2.0"
TARGET_PATTERN = r"\.\s*system_monitor_loop\s*\.\s*start\s*\(\s*\)"
auto_fix = False  # 若要自动替换，可设为 True

print(f"🔍 开始扫描项目目录: {PROJECT_DIR}")
print(f"🛠️ 自动修复: {'启用' if auto_fix else '禁用'}")
print("------------------------------------------------------------")

def scan_file(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        modified = False
        for idx, line in enumerate(lines):
            if re.search(TARGET_PATTERN, line):
                print(f"❗ 发现误用: {file_path}:{idx+1}")
                print(f"    原始代码: {line.strip()}")
                if auto_fix:
                    # 替换为正确方式（比如 system_monitor.start()）
                    lines[idx] = re.sub(TARGET_PATTERN, ".start()", line)
                    modified = True

        if modified:
            with open(file_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            print(f"✅ 已自动修复: {file_path}")
    except Exception as e:
        print(f"⚠️ 跳过文件（读取失败）: {file_path} | 错误: {e}")

for root, dirs, files in os.walk(PROJECT_DIR):
    for file in files:
        if file.endswith(".py"):
            scan_file(os.path.join(root, file))

print("------------------------------------------------------------")
print("✅ 扫描完成")
