import os
import re

def fix_logger_calls_in_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    pattern = re.compile(r'(logger\.\w+)\((.*extra=\{[^}]*\}\))')
    fixed_lines = []
    changed = False

    for line in lines:
        # 先查找是否有 logger.xxx( ... extra={ ... } )
        match = re.search(r'(logger\.\w+\(.*extra=\{[^}]*\}.*\))', line)
        if match:
            # 简单判断括号是否匹配，发现')'数量少于'('时补齐
            open_paren = line.count('(')
            close_paren = line.count(')')
            if close_paren < open_paren:
                line = line.rstrip('\n') + (')' * (open_paren - close_paren)) + '\n'
                changed = True
        fixed_lines.append(line)

    if changed:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.writelines(fixed_lines)
        print(f"Fixed parentheses in {filepath}")

def fix_dir(root_dir):
    for dirpath, _, filenames in os.walk(root_dir):
        for fn in filenames:
            if fn.endswith('.py'):
                fix_logger_calls_in_file(os.path.join(dirpath, fn))

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python fix_logger_extra_parens.py <path_to_directory>")
        sys.exit(1)
    fix_dir(sys.argv[1])
