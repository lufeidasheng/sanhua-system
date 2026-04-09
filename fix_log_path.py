import os
import re

MODULES_DIR = 'modules'
LOGS_BASE_DIR = 'logs'

def fix_file(file_path, module_name):
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    new_lines = []
    inserted_import_os = False
    inserted_makedirs = False
    log_dir_var = 'log_dir'

    # 判断是否已导入 os
    for line in lines:
        if re.match(r'^\s*import\s+os', line):
            inserted_import_os = True
            break

    for i, line in enumerate(lines):
        # 替换 /var/log/xxx 路径
        if '"/var/log' in line or "'/var/log" in line:
            # 用项目内相对路径替换
            new_line = re.sub(
                r'["\']\/var\/log\/[^\"]*["\']',
                f'os.path.join(os.path.dirname(__file__), "..", "..", "{LOGS_BASE_DIR}", "{module_name}")',
                line
            )
            new_lines.append(new_line)
            # 在此文件首次替换时，后面加上 makedirs 创建目录代码
            if not inserted_makedirs:
                # 先插入 os.makedirs 行（下一行插入）
                new_lines.append(f'{log_dir_var} = os.path.abspath({log_dir_var})\n')
                new_lines.append(f'os.makedirs({log_dir_var}, exist_ok=True)\n')
                inserted_makedirs = True
        else:
            new_lines.append(line)

    # 如果没有 import os，添加一行import os，放在文件开头第一个非注释行前
    if not inserted_import_os:
        for i, line in enumerate(new_lines):
            if line.strip() and not line.strip().startswith('#'):
                new_lines.insert(i, 'import os\n')
                break

    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    print(f"✅ 修正日志路径并写入文件: {file_path}")

def main():
    for root, dirs, files in os.walk(MODULES_DIR):
        for file in files:
            if file.endswith('.py'):
                full_path = os.path.join(root, file)
                module_name = os.path.basename(root)
                fix_file(full_path, module_name)

if __name__ == '__main__':
    main()

