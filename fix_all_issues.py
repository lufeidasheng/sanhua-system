import os
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CORE_DIR = BASE_DIR / 'core' / 'core.core2_0'
CONFIG_FILE = BASE_DIR / 'core' / 'config.py'
EVENT_BUS_FILE = CORE_DIR / 'event_bus.py'
AICORE_DIR = CORE_DIR / 'aicore'
AICORE_INIT = AICORE_DIR / '__init__.py'

def fix_event_bus_time_comparison():
    print("[1] 修复 event_bus.py 时间比较问题...")
    if not EVENT_BUS_FILE.exists():
        print("  [跳过] event_bus.py 文件不存在")
        return

    with EVENT_BUS_FILE.open('r', encoding='utf-8') as f:
        code = f.read()

    if 'cert.not_valid_before_utc' in code:
        fixed_code = re.sub(
            r'cert\.not_valid_before_utc',
            'cert.not_valid_before.replace(tzinfo=None)',
            code
        )
        fixed_code = re.sub(
            r'cert\.not_valid_after_utc',
            'cert.not_valid_after.replace(tzinfo=None)',
            fixed_code
        )
        with EVENT_BUS_FILE.open('w', encoding='utf-8') as f:
            f.write(fixed_code)
        print("  [已修复] 已替换为 tz-aware 安全比较")
    else:
        print("  [跳过] 未检测到旧时间字段")

def fix_module_import_error():
    print("[2] 修复 aicore 模块导入问题...")
    if not AICORE_DIR.exists():
        print("  [创建中] 缺失目录: core/core.core2_0/aicore")
        AICORE_DIR.mkdir(parents=True, exist_ok=True)

    if not AICORE_INIT.exists():
        print("  [创建中] 缺失 __init__.py")
        AICORE_INIT.write_text("# 自动创建 __init__.py\n", encoding='utf-8')
    else:
        print("  [跳过] __init__.py 已存在")

def fix_config_attributes():
    print("[3] 检查并补全 config.py 配置项...")
    if not CONFIG_FILE.exists():
        print("  [错误] 缺失 config.py 文件")
        return

    with CONFIG_FILE.open('r', encoding='utf-8') as f:
        lines = f.readlines()

    config_map = {
        "REPLY_THREAD_POOL_SIZE": "8"
    }

    existing_keys = [line.strip().split('=')[0] for line in lines if '=' in line]
    with CONFIG_FILE.open('a', encoding='utf-8') as f:
        for key, value in config_map.items():
            if key not in existing_keys:
                f.write(f"\n{key} = {value}  # 自动修复添加\n")
                print(f"  [已添加] {key} = {value}")
            else:
                print(f"  [跳过] {key} 已存在")

def main():
    print("🛠 三花聚顶 修复脚本开始执行...\n")
    fix_event_bus_time_comparison()
    fix_module_import_error()
    fix_config_attributes()
    print("\n✅ 修复完成，请重新运行你的 CLI 程序试试。")

if __name__ == "__main__":
    main()
