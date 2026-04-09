import os
import sys
import py_compile

def check_syntax_errors(root_dir):
    error_files = []
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.endswith('.py'):
                filepath = os.path.join(dirpath, filename)
                try:
                    py_compile.compile(filepath, doraise=True)
                except py_compile.PyCompileError as e:
                    error_files.append((filepath, e))
    return error_files

def main(root_dir):
    errors = check_syntax_errors(root_dir)
    if not errors:
        print("所有 Python 文件语法检查通过！")
    else:
        print(f"发现 {len(errors)} 个语法错误文件：")
        for filepath, error in errors:
            print(f"\n文件: {filepath}\n错误信息:\n{error}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python check_syntax.py <目录路径>")
        sys.exit(1)
    root_dir = sys.argv[1]
    main(root_dir)
