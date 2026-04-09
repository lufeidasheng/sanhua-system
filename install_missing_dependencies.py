import os
import re
import subprocess
import sys

# Python 内建标准库模块（仅常见部分）
STANDARD_LIBS = {
    'os', 'sys', 're', 'math', 'time', 'json', 'logging', 'threading',
    'asyncio', 'itertools', 'collections', 'subprocess', 'typing',
    'datetime', 'pathlib', 'http', 'unittest', 'copy', 'queue', 'functools',
    'importlib', 'inspect', 'shutil', 'uuid', 'base64', 'dataclasses'
}

MODULES_DIR = "modules"

def extract_imports_from_file(filepath):
    imports = set()
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            match_import = re.match(r'^\s*import\s+([\w_]+)', line)
            match_from = re.match(r'^\s*from\s+([\w_]+)', line)
            if match_import:
                imports.add(match_import.group(1))
            elif match_from:
                imports.add(match_from.group(1))
    return imports

def get_all_imports():
    all_imports = set()
    for root, dirs, files in os.walk(MODULES_DIR):
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                all_imports.update(extract_imports_from_file(path))
    return all_imports

def install_missing_packages(imports):
    third_party = sorted(set(imports) - STANDARD_LIBS)
    print(f"\n🔍 检测到可能缺失的第三方库：{third_party}\n")
    for pkg in third_party:
        try:
            __import__(pkg)
        except ImportError:
            print(f"📦 正在安装缺失库：{pkg} ...")
            subprocess.run([sys.executable, "-m", "pip", "install", pkg])
        else:
            print(f"✅ 已安装：{pkg}")

if __name__ == "__main__":
    all_imports = get_all_imports()
    install_missing_packages(all_imports)
    print("\n🎉 所有依赖库检查与安装完成。")
