import importlib
import os
import json

MODULES_DIR = "./modules"

def test_all_modules_register_actions():
    for name in os.listdir(MODULES_DIR):
        module_path = os.path.join(MODULES_DIR, name)
        manifest_path = os.path.join(module_path, "manifest.json")
        if os.path.isdir(module_path) and os.path.exists(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as f:
                info = json.load(f)
                entry_file = info.get("entry_file", "main.py")
                module_name = f"modules.{name}.{entry_file.replace('.py', '')}"
                try:
                    m = importlib.import_module(module_name)
                    assert hasattr(m, "register_actions")
                except Exception as e:
                    pytest.fail(f"模块 {name} 加载失败: {e}")
