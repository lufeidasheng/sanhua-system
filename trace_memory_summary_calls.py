import os
import re

# 配置你的项目根目录
PROJECT_ROOT = "./"  # 当前目录，也可以替换为 "/path/to/your/project"

# 目标调用的正则
TARGET_CALL = r"core\.memory_manager\.get_memory_summary\s*\("

def search_calls(root_dir, pattern):
    results = []
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.endswith(".py"):
                filepath = os.path.join(dirpath, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                        for i, line in enumerate(lines):
                            if re.search(pattern, line):
                                results.append((filepath, i+1, line.strip()))
                except Exception as e:
                    print(f"读取失败: {filepath}: {e}")
    return results

def main():
    print("开始搜索调用 core.memory_manager.get_memory_summary() 的位置...\n")
    matches = search_calls(PROJECT_ROOT, TARGET_CALL)
    if not matches:
        print("未找到任何调用。")
        return

    for filepath, lineno, line in matches:
        print(f"[命中] {filepath}:{lineno}\n  ↳ {line}\n")

if __name__ == "__main__":
    main()
