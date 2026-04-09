import logging
import importlib

def check_imports(base_path):
    logging.info("开始检测模块导入情况...")

    # 列出需要检测的模块全路径（包名形式）
    modules_to_check = [
        "core.aicore",
        "core.core2_0.event_bus",
        "entry.cli_entry.cli_entry",
    ]

    for mod in modules_to_check:
        try:
            importlib.import_module(mod)
            logging.info(f"模块导入成功: {mod}")
        except ModuleNotFoundError as e:
            logging.error(f"模块导入失败: {mod}，错误: {e}")

    logging.info("模块导入检测完成。")
