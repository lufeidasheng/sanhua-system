import json
import importlib
import os
import threading

class ModuleLoader:
    def __init__(self, module_path: str):
        self.module_path = module_path
        self.module_info = None
        self.module_instance = None

    def load_manifest(self):
        manifest_file = os.path.join(self.module_path, "manifest.json")
        if not os.path.exists(manifest_file):
            raise FileNotFoundError(f"Manifest not found in {self.module_path}")
        with open(manifest_file, "r", encoding="utf-8") as f:
            self.module_info = json.load(f)

    def load_module(self):
        if not self.module_info:
            self.load_manifest()

        entry_file = self.module_info.get("entry")
        if not entry_file:
            raise ValueError("Entry file not specified in manifest")

        # 转换文件名为模块路径，比如 aicore.py -> aicore
        module_name = os.path.splitext(entry_file)[0]
        module_full_path = f"{os.path.basename(self.module_path)}.{module_name}"

        # 动态导入模块
        module = importlib.import_module(module_full_path)

        # 假设入口类名和模块名相同且首字母大写，如 aicore -> AICore
        class_name = module_name.capitalize()
        cls = getattr(module, class_name)

        # 创建模块实例
        self.module_instance = cls()

    def get_instance(self):
        if self.module_instance is None:
            self.load_module()
        return self.module_instance

# 测试用例
if __name__ == "__main__":
    loader = ModuleLoader("aicore")
    ai_core = loader.get_instance()
    print(ai_core.chat("测试聚核助手聊天"))
