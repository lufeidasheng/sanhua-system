import os
import re

PROJECT_ROOT = '/home/lufei/文档/聚核助手2.0/core.core2_0/sanhuatongyu'

LOG_METHODS = ['debug', 'info', 'warning', 'error', 'critical']

LOG_CALL_RE = re.compile(
    r'(\.\s*({})\s*\()([^\)]*?)\)'.format('|'.join(LOG_METHODS)),
    re.DOTALL
)

KWARG_RE = re.compile(r'(\b(error|traceback|msg|extra)\s*=\s*[^,]+)(,?)')

def replace_log_call(match):
    full_call = match.group(0)
    method = match.group(2)
    args_str = match.group(3)

    if 'extra=' in args_str:
        return full_call

    kwargs = KWARG_RE.findall(args_str)
    if not kwargs:
        return full_call

    extra_items = []
    other_args = []

    parts = [p.strip() for p in args_str.split(',') if p.strip()]

    for p in parts:
        if p.startswith('error=') or p.startswith('traceback='):
            extra_items.append(p)
        else:
            other_args.append(p)

    if not extra_items:
        return full_call

    extra_dict_items = []
    for item in extra_items:
        key, val = item.split('=', 1)
        extra_dict_items.append(f'"{key.strip()}": {val.strip()}')
    extra_str = 'extra={' + ', '.join(extra_dict_items) + '}'

    new_args = other_args + [extra_str]
    new_args_str = ', '.join(new_args)

    return f'.{method}({new_args_str})'

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    new_content, count = LOG_CALL_RE.subn(replace_log_call, content)

    if count > 0:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f'Updated {count} log call(s) in {filepath}')

def main():
    for root, dirs, files in os.walk(PROJECT_ROOT):
        for file in files:
            if file.endswith('.py'):
                process_file(os.path.join(root, file))

if __name__ == '__main__':
    main()
