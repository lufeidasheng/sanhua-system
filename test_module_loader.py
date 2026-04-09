import unittest
import tempfile
import shutil
import sys
import time
import asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# 请根据你的项目实际路径调整
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.core2_0.module_loader import ModuleLoader

class DummyDispatcher:
    def __init__(self):
        self.registered = {}
        self.cleared_modules = []

    def register_action(self, name, func):
        self.registered[name] = func

    def clear_actions_by_module(self, module_name):
        self.cleared_modules.append(module_name)
        to_remove = [k for k, v in self.registered.items() if hasattr(v, '__module__') and v.__module__.endswith(module_name)]
        for k in to_remove:
            self.registered.pop(k)

class DummyEventBus:
    def __init__(self):
        self.subscribed = {}
        self.emitted = []

    def subscribe(self, event_type, handler):
        self.subscribed.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type, handler):
        if event_type in self.subscribed:
            try:
                self.subscribed[event_type].remove(handler)
            except ValueError:
                pass

    def emit(self, event_type, payload=None):
        self.emitted.append((event_type, payload))
        for handler in self.subscribed.get(event_type, []):
            handler(payload)

    def is_initialized(self):
        return True

class TestModuleLoader(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.dispatcher = DummyDispatcher()
        self.event_bus = DummyEventBus()
        self._create_example_module()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def _create_example_module(self):
        code = '''\
__version__ = "1.0.0"
__depends__ = []

def register_actions(dispatcher):
    dispatcher.register_action("test_action", lambda: "hello")

def initialize():
    print("init example_module")
    return True

def cleanup():
    print("cleanup example_module")
    return True

event_handlers = {
    "test.event": lambda e: print(f"Handled event: {e}")
}
'''
        (Path(self.test_dir) / "example_module.py").write_text(code, encoding="utf-8")

    def _create_dependent_module(self):
        code = '''\
__version__ = "1.0.0"
__depends__ = ["example_module"]

def initialize():
    print("init dependent_module")
    return True

def cleanup():
    print("cleanup dependent_module")
    return True
'''
        (Path(self.test_dir) / "dependent_module.py").write_text(code, encoding="utf-8")

    def _create_circular_modules(self):
        code_a = '''\
__version__ = "1.0.0"
__depends__ = ["circular_b"]

def initialize():
    print("init circular_a")
    return True
'''
        code_b = '''\
__version__ = "1.0.0"
__depends__ = ["circular_a"]

def initialize():
    print("init circular_b")
    return True
'''
        (Path(self.test_dir) / "circular_a.py").write_text(code_a, encoding="utf-8")
        (Path(self.test_dir) / "circular_b.py").write_text(code_b, encoding="utf-8")

    def _create_async_module(self):
        code = '''\
__version__ = "1.0.0"
__depends__ = []

async def initialize():
    print("async init module")
    return True

async def cleanup():
    print("async cleanup module")
    return True
'''
        (Path(self.test_dir) / "async_mod.py").write_text(code, encoding="utf-8")

    def test_basic_load_unload(self):
        loader = ModuleLoader(
            modules_dir=self.test_dir,
            dispatcher=self.dispatcher,
            event_bus=self.event_bus,
            security_check=False
        )
        success, failure = loader.load_all_modules()
        self.assertEqual(success, 1)
        self.assertEqual(failure, 0)
        self.assertIn("example_module", loader.loaded_modules)
        self.assertIn("test_action", self.dispatcher.registered)
        self.assertIn("test.event", self.event_bus.subscribed)

        # 测试卸载
        result = loader.unload_module("example_module")
        self.assertTrue(result)
        self.assertNotIn("example_module", loader.loaded_modules)
        self.assertNotIn("test_action", self.dispatcher.registered)
        self.assertNotIn("test.event", self.event_bus.subscribed)

    def test_dependency_loading(self):
        self._create_dependent_module()
        loader = ModuleLoader(
            modules_dir=self.test_dir,
            dispatcher=self.dispatcher,
            event_bus=self.event_bus,
            security_check=False
        )
        success, failure = loader.load_all_modules()
        self.assertEqual(success, 2)
        self.assertEqual(failure, 0)
        self.assertIn("dependent_module", loader.loaded_modules)
        self.assertIn("example_module", loader.dependency_graph["dependent_module"])

    def test_circular_dependency_detection(self):
        self._create_circular_modules()
        loader = ModuleLoader(
            modules_dir=self.test_dir,
            dispatcher=self.dispatcher,
            event_bus=self.event_bus,
            security_check=False
        )
        loader.load_all_modules()
        cycles = loader.check_circular_deps()
        self.assertTrue(any("circular_a" in cycle and "circular_b" in cycle for cycle in cycles))
        # 确认循环依赖模块不会加载成功
        self.assertNotIn("circular_a", loader.loaded_modules)
        self.assertNotIn("circular_b", loader.loaded_modules)

    def test_async_module(self):
        self._create_async_module()
        loader = ModuleLoader(
            modules_dir=self.test_dir,
            dispatcher=self.dispatcher,
            event_bus=self.event_bus,
            security_check=False
        )
        success, failure = loader.load_all_modules()
        self.assertIn("async_mod", loader.loaded_modules)
        self.assertTrue(loader.loaded_modules["async_mod"].initialized)
        result = loader.unload_module("async_mod")
        self.assertTrue(result)
        self.assertNotIn("async_mod", loader.loaded_modules)

    def test_security_check(self):
        dangerous_code = '''\
def initialize():
    import os
    os.system("echo dangerous")
    return True

__depends__ = []
'''
        (Path(self.test_dir) / "dangerous_mod.py").write_text(dangerous_code, encoding="utf-8")
        secure_loader = ModuleLoader(
            modules_dir=self.test_dir,
            security_check=True
        )
        success, failure = secure_loader.load_all_modules()
        self.assertEqual(failure, 1)
        self.assertNotIn("dangerous_mod", secure_loader.loaded_modules)

        insecure_loader = ModuleLoader(
            modules_dir=self.test_dir,
            security_check=False
        )
        success, failure = insecure_loader.load_all_modules()
        self.assertIn("dangerous_mod", insecure_loader.loaded_modules)

    def test_reload_module(self):
        loader = ModuleLoader(
            modules_dir=self.test_dir,
            dispatcher=self.dispatcher,
            event_bus=self.event_bus,
            security_check=False
        )
        loader.load_all_modules()
        example_path = Path(self.test_dir) / "example_module.py"
        new_content = example_path.read_text() + "\n# Added comment for reload test"
        example_path.write_text(new_content)
        result = loader.reload_module("example_module")
        self.assertTrue(result)
        self.assertIn("example_module", loader.loaded_modules)

    def test_hot_reload(self):
        loader = ModuleLoader(
            modules_dir=self.test_dir,
            dispatcher=self.dispatcher,
            event_bus=self.event_bus,
            enable_hotreload=True,
            security_check=False
        )
        loader.load_all_modules()
        example_path = Path(self.test_dir) / "example_module.py"
        original_content = example_path.read_text()
        example_path.write_text(original_content + "\n# hot reload test")
        time.sleep(1.5)  # 给热重载时间触发
        self.assertIn("example_module", loader.loaded_modules)
        example_path.write_text(original_content)

    def test_concurrent_loading(self):
        loader = ModuleLoader(
            modules_dir=self.test_dir,
            dispatcher=self.dispatcher,
            event_bus=self.event_bus,
            security_check=False
        )
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(loader.load_all_modules) for _ in range(3)]
            results = [f.result() for f in futures]
        for success, failure in results:
            self.assertTrue(success >= 1)
            self.assertEqual(failure, 0)
        self.assertEqual(len(loader.loaded_modules), 1)

    def test_get_module_info_and_shutdown(self):
        loader = ModuleLoader(
            modules_dir=self.test_dir,
            dispatcher=self.dispatcher,
            event_bus=self.event_bus,
            security_check=False
        )
        loader.load_all_modules()
        mod = loader.get_module("example_module")
        self.assertIsNotNone(mod)
        mods = loader.list_modules()
        self.assertIn("example_module", mods)
        dependents = loader.get_dependents("example_module")
        self.assertIsInstance(dependents, list)
        loader.shutdown()
        self.assertEqual(len(loader.loaded_modules), 0)

if __name__ == "__main__":
    unittest.main()
