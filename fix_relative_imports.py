import os
import re

def replace_imports_in_file(filepath, package_dir):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    original_content = content

    # 替换 'from aicore.xxx import ...' 或 'import aicore.xxx'
    if package_dir == 'aicore':
        # aicore -> 相对导入 .
        content = re.sub(r'from\s+aicore(\.[\w\.]+)?\s+import', r'from .\1 import', content)
        content = re.sub(r'import\s+aicore(\.[\w\.]+)?', lambda m: 'import .' + (m.group(1) or ''), content)

    elif package_dir == 'core.core2_0':
        # core.core2_0 -> 相对导入 .
        content = re.sub(r'from\s+core.core2_0(\.[\w\.]+)?\s+import', r'from .\1 import', content)
        content = re.sub(r'import\s+core.core2_0(\.[\w\.]+)?', lambda m: 'import .' + (m.group(1) or ''), content)

    if content != original_content:
        print(f"更新文件: {filepath}")
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

def process_directory(base_path, package_dir):
    target_dir = os.path.join(base_path, package_dir)
    for root, dirs, files in os.walk(target_dir):
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                replace_imports_in_file(filepath, package_dir)

if __name__ == '__main__':
    base_path = os.path.abspath('core')
    process_directory(base_path, 'aicore')
    process_directory(base_path, 'core.core2_0')
