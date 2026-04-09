# fix_imports.py
import os

project_root = '/home/lufei/文档/聚核助手2.0'

def fix_aicore_imports():
    for dirpath, _, files in os.walk(project_root):
        for file in files:
            if file.endswith('.py'):
                path = os.path.join(dirpath, file)
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()

                new_content = content.replace('core.aicore', 'core.aicore')

                if new_content != content:
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    print(f'✅ 修复导入路径: {path}')

if __name__ == '__main__':
    fix_aicore_imports()
