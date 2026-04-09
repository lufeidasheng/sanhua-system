import os
import sys
import importlib
import logging
import datetime

logging.basicConfig(
    format='[%(asctime)s] %(levelname)s - %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))

# 关键路径和文件
REQUIRED_PATHS = [
    os.path.join(PROJECT_ROOT, 'core'),
    os.path.join(PROJECT_ROOT, 'entry'),
    os.path.join(PROJECT_ROOT, 'modules'),
    os.path.join(PROJECT_ROOT, 'certs'),
]

REQUIRED_FILES = [
    os.path.join(PROJECT_ROOT, 'config.py'),
    os.path.join(PROJECT_ROOT, 'certs', 'eventbus.crt'),
    os.path.join(PROJECT_ROOT, 'certs', 'ca-bundle.crt'),
]

MODULES_TO_TEST = [
    'core.core2_0.aicore',
    'entry.cli_entry.cli_entry'
]

PERMISSION_PATHS = [
    '/var/lib/aicore'  # 你可以根据实际调整
]

def ensure_directories():
    for path in REQUIRED_PATHS:
        if not os.path.exists(path):
            logging.warning(f"缺失目录，自动创建：{path}")
            try:
                os.makedirs(path)
            except Exception as e:
                logging.error(f"创建目录失败：{path}，错误：{e}")
        else:
            logging.info(f"目录存在：{path}")

def ensure_files():
    for filepath in REQUIRED_FILES:
        if not os.path.isfile(filepath):
            logging.warning(f"缺失文件，自动创建占位文件：{filepath}")
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    if filepath.endswith('.py'):
                        f.write("# 自动生成默认配置文件，请根据需要修改\nREPLY_PROCESSING_TIMEOUT = 30\n")
                    else:
                        f.write("-----BEGIN CERTIFICATE-----\nPLACEHOLDER\n-----END CERTIFICATE-----\n")
            except Exception as e:
                logging.error(f"创建文件失败：{filepath}，错误：{e}")
        else:
            logging.info(f"文件存在：{filepath}")

def fix_sys_path():
    # 确保项目根目录加入sys.path，方便模块导入
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)
        logging.info(f"已将项目根目录添加到 sys.path：{PROJECT_ROOT}")

def test_module_import(module_name):
    logging.info(f"尝试导入模块：{module_name}")
    try:
        importlib.import_module(module_name)
        logging.info(f"模块导入成功：{module_name}")
    except Exception as e:
        logging.error(f"模块导入失败：{module_name}，错误：{e}")

def check_permissions():
    for path in PERMISSION_PATHS:
        if not os.path.exists(path):
            logging.warning(f"权限路径不存在：{path}，尝试创建...")
            try:
                os.makedirs(path)
                logging.info(f"创建权限路径成功：{path}")
            except Exception as e:
                logging.error(f"创建权限路径失败：{path}，错误：{e}")
        if not os.access(path, os.W_OK):
            logging.error(f"无写权限：{path}，请手动调整权限或使用sudo运行")

def fix_datetime_error():
    # 典型错误示范：offset-naive 与 offset-aware datetime比较
    logging.info("检测并修复 datetime 比较问题（如有）")
    try:
        # 这里仅给出提醒，具体代码需在你的模块 event_bus.py 中修改
        import core.core2_0.event_bus as event_bus
        # 仅检查函数，不自动修改，提示用户修复
        logging.info("请确认 event_bus.py 中所有 datetime 比较，避免 offset-naive 与 offset-aware 混用。")
    except Exception as e:
        logging.warning(f"无法检查 datetime 修复，错误：{e}")

def main():
    logging.info("🚑 Sanhua 系统智能自愈器启动")

    ensure_directories()
    ensure_files()
    fix_sys_path()

    for module in MODULES_TO_TEST:
        test_module_import(module)

    check_permissions()

    fix_datetime_error()

    logging.info("✅ 自愈检测和修复尝试完成")

if __name__ == "__main__":
    main()
