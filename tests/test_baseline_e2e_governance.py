import importlib
import json
import textwrap
import time
import types
from pathlib import Path
import sys
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.core2_0.sanhuatongyu import context_factory
from core.core2_0.sanhuatongyu.module import manager as module_manager_mod
from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER, dispatcher
from core.core2_0.sanhuatongyu.context import SystemContext
from core.core2_0.sanhuatongyu.execution_planner import ExecutionPlanner, PlanStep
from core.core2_0.sanhuatongyu.system_module import SystemModule
from core.gui_bridge import chat_orchestrator as chat_mod
from core.gui_bridge import gui_memory_bridge
from core.gui_bridge.chat_orchestrator import GUIChatOrchestrator
from entry.cli_entry.cli_entry import SanhuaCmdShell
from modules.reply_dispatcher import module as reply_dispatcher_mod


class FakeModuleManager:
    def health_check(self):
        return {
            "status": "ok",
            "health": "OK",
            "modules": {
                "fake_module": {
                    "status": "OK",
                    "reason": "baseline_e2e_stub",
                }
            },
        }


class FakeLifecycleModule:
    def __init__(self):
        self.start_count = 0
        self.post_start_count = 0
        self.stop_count = 0
        self.shutdown_count = 0

    def start(self):
        self.start_count += 1

    def post_start(self):
        self.post_start_count += 1

    def stop(self):
        self.stop_count += 1

    def on_shutdown(self):
        self.shutdown_count += 1


class FakeObserver:
    instances = []

    def __init__(self):
        self.schedules = []
        self.start_count = 0
        self.stop_count = 0
        self.join_count = 0
        self.alive = False
        self.started_once = False
        FakeObserver.instances.append(self)

    def schedule(self, handler, path, recursive=True):
        self.schedules.append((handler, path, recursive))

    def is_alive(self):
        return self.alive

    def start(self):
        if self.started_once:
            raise RuntimeError("threads can only be started once")
        self.started_once = True
        self.start_count += 1
        self.alive = True

    def stop(self):
        self.stop_count += 1
        self.alive = False

    def join(self):
        self.join_count += 1


class FakeReplyThread:
    instances = []

    def __init__(self, target=None, daemon=None, name=None):
        self.target = target
        self.daemon = daemon
        self.name = name
        self.start_count = 0
        self.join_count = 0
        self.alive = False
        self.started_once = False
        FakeReplyThread.instances.append(self)

    def is_alive(self):
        return self.alive

    def start(self):
        if self.started_once:
            raise RuntimeError("threads can only be started once")
        self.started_once = True
        self.start_count += 1
        self.alive = True

    def join(self, timeout=None):
        self.join_count += 1
        self.alive = False


class FakeReplyFuture:
    def add_done_callback(self, _callback):
        return None


class FakeReplyExecutor:
    instances = []

    def __init__(self, max_workers=None, thread_name_prefix=None):
        self.max_workers = max_workers
        self.thread_name_prefix = thread_name_prefix
        self.shutdown_count = 0
        self.submit_count = 0
        self._shutdown = False
        self._work_queue = SimpleNamespace(qsize=lambda: 0)
        self._max_workers = max_workers
        FakeReplyExecutor.instances.append(self)

    def submit(self, *_args, **_kwargs):
        if self._shutdown:
            raise RuntimeError("cannot schedule new futures after shutdown")
        self.submit_count += 1
        return FakeReplyFuture()

    def shutdown(self, wait=True):
        self.shutdown_count += 1
        self._shutdown = True


def _make_module_manager(monkeypatch, tmp_path):
    FakeObserver.instances = []
    monkeypatch.setattr(module_manager_mod, "Observer", FakeObserver)
    context = SimpleNamespace(action_dispatcher=object())
    return module_manager_mod.ModuleManager(str(tmp_path), context)


def _make_reply_dispatcher(monkeypatch):
    FakeReplyThread.instances = []
    FakeReplyExecutor.instances = []
    monkeypatch.setattr(reply_dispatcher_mod.threading, "Thread", FakeReplyThread)
    monkeypatch.setattr(reply_dispatcher_mod, "ThreadPoolExecutor", FakeReplyExecutor)
    monkeypatch.setattr(reply_dispatcher_mod, "is_event_bus_initialized", lambda: False)
    meta = SimpleNamespace(name="reply_dispatcher")
    context = SimpleNamespace()
    return reply_dispatcher_mod.ReplyDispatcherModule(meta, context)


def _install_fake_module_manager(monkeypatch):
    def fake_ensure_module_manager(context, entry_mode, log):
        context.module_manager = FakeModuleManager()

    monkeypatch.setattr(context_factory, "_ensure_module_manager", fake_ensure_module_manager)


def _create_stubbed_context(monkeypatch):
    _install_fake_module_manager(monkeypatch)
    return context_factory.create_system_context(entry_mode="gui")


def test_context_call_action_reaches_system_health_check_through_dispatcher(monkeypatch):
    ctx = _create_stubbed_context(monkeypatch)

    result = ctx.call_action("system.health_check", params={"probe": "baseline_e2e"})

    assert ctx.action_dispatcher is dispatcher
    assert ACTION_MANAGER is dispatcher
    assert result["health"] == "OK"
    assert result["modules"]["fake_module"]["reason"] == "baseline_e2e_stub"


def test_context_call_action_prefers_dispatcher_call_action_for_standard_params():
    calls = []

    class FakeDispatcher:
        def call_action(self, name, params=None, **kwargs):
            calls.append(("call_action", name, params, kwargs))
            return {"ok": True, "name": name, "params": params, "kwargs": kwargs}

        def execute(self, *args, **kwargs):
            raise AssertionError("standard context.call_action must not bypass dispatcher.call_action")

    ctx = SimpleNamespace(action_dispatcher=FakeDispatcher())

    result = SystemContext.call_action(
        ctx,
        "demo.action",
        params={"query": "hello"},
        trace_id="dispatch-governance",
    )

    assert result == {
        "ok": True,
        "name": "demo.action",
        "params": {"query": "hello"},
        "kwargs": {"trace_id": "dispatch-governance"},
    }
    assert calls == [
        (
            "call_action",
            "demo.action",
            {"query": "hello"},
            {"trace_id": "dispatch-governance"},
        )
    ]


def test_context_call_action_rejects_legacy_positional_args():
    class FakeDispatcher:
        def call_action(self, *args, **kwargs):
            raise AssertionError("legacy positional args must be rejected before dispatcher")

        def execute(self, *args, **kwargs):
            raise AssertionError("call_action must not route legacy positional args to execute")

    ctx = SimpleNamespace(action_dispatcher=FakeDispatcher())

    try:
        SystemContext.call_action(ctx, "demo.action", "legacy-query")
    except TypeError as exc:
        assert "execute_action" in str(exc)
    else:
        raise AssertionError("SystemContext.call_action should reject legacy positional args")


def test_context_call_action_rejects_non_dict_params():
    class FakeDispatcher:
        def call_action(self, *args, **kwargs):
            raise AssertionError("non-dict params must be rejected before dispatcher")

        def execute(self, *args, **kwargs):
            raise AssertionError("call_action must not route non-dict params to execute")

    ctx = SimpleNamespace(action_dispatcher=FakeDispatcher())

    try:
        SystemContext.call_action(ctx, "demo.action", params="not-a-dict")
    except TypeError as exc:
        assert "params" in str(exc)
    else:
        raise AssertionError("SystemContext.call_action should reject non-dict params")


def test_context_execute_action_remains_legacy_execute_bridge():
    calls = []

    class FakeDispatcher:
        def call_action(self, *args, **kwargs):
            raise AssertionError("execute_action must not route through call_action")

        def execute(self, name, *args, **kwargs):
            calls.append((name, args, kwargs))
            return {"ok": True, "bridge": "execute"}

    ctx = SimpleNamespace(action_dispatcher=FakeDispatcher())

    result = SystemContext.execute_action(
        ctx,
        "demo.action",
        "legacy-query",
        mode="compat",
    )

    assert result == {"ok": True, "bridge": "execute"}
    assert calls == [("demo.action", ("legacy-query",), {"mode": "compat"})]


def test_context_list_actions_supports_detailed_discovery():
    calls = []

    class FakeDispatcher:
        def list_actions(self, module=None, detailed=False):
            calls.append((module, detailed))
            return [{"name": "demo.action", "owner": module or "system", "detailed": detailed}]

    ctx = SimpleNamespace(action_dispatcher=FakeDispatcher())

    result = SystemContext.list_actions(ctx, module="demo", detailed=True)

    assert result == [{"name": "demo.action", "owner": "demo", "detailed": True}]
    assert calls == [("demo", True)]


def test_context_list_actions_without_dispatcher_is_safe():
    ctx = SimpleNamespace()

    assert SystemContext.list_actions(ctx, detailed=True) == []


def test_context_get_system_health_uses_module_manager_health_check():
    class FakeModuleManager:
        def health_check(self):
            return {
                "status": "ok",
                "health": "OK",
                "modules": {"demo": {"status": "OK"}},
            }

    ctx = SimpleNamespace(module_manager=FakeModuleManager())

    result = SystemContext.get_system_health(ctx)

    assert result["status"] == "ok"
    assert result["health"] == "OK"
    assert result["modules"]["demo"]["status"] == "OK"


def test_context_get_system_health_without_module_manager_degrades():
    ctx = SimpleNamespace()

    result = SystemContext.get_system_health(ctx)

    assert result == {"status": "unknown", "health": "UNKNOWN", "modules": {}}


def test_context_get_system_status_returns_lightweight_snapshot():
    ctx = SimpleNamespace(
        system_running=True,
        start_time=time.time() - 12,
        module_manager=SimpleNamespace(loaded_modules={"a": object(), "b": object()}),
    )

    result = SystemContext.get_system_status(ctx)

    assert result["status"] == "RUNNING"
    assert result["system_running"] is True
    assert result["modules_loaded"] == 2
    assert result["uptime"] >= 0


def test_context_get_system_status_without_fields_degrades():
    ctx = SimpleNamespace()

    result = SystemContext.get_system_status(ctx)

    assert result == {
        "status": "UNKNOWN",
        "system_running": False,
        "uptime": 0.0,
        "modules_loaded": 0,
    }


def test_context_get_loaded_modules_uses_module_manager_listing():
    class FakeModuleManager:
        def list_all_modules(self):
            return ["alpha", "beta"]

    ctx = SimpleNamespace(module_manager=FakeModuleManager())

    result = SystemContext.get_loaded_modules(ctx)

    assert result == ["alpha", "beta"]


def test_context_get_loaded_modules_falls_back_to_loaded_modules_dict():
    ctx = SimpleNamespace(module_manager=SimpleNamespace(loaded_modules={"alpha": object(), "beta": object()}))

    result = SystemContext.get_loaded_modules(ctx)

    assert result == ["alpha", "beta"]


def test_context_get_loaded_modules_without_module_manager_degrades():
    ctx = SimpleNamespace()

    assert SystemContext.get_loaded_modules(ctx) == []


def _load_gui_mainwindow_list_actions_method():
    source = (PROJECT_ROOT / "entry/gui_entry/gui_main.py").read_text(encoding="utf-8")
    start = source.index("    def _list_actions(self):")
    end = source.index("    def _has_action", start)
    namespace = {}
    exec(textwrap.dedent(source[start:end]), namespace)
    return namespace["_list_actions"], source[start:end]


def test_gui_list_actions_uses_context_standard_interface():
    method, source = _load_gui_mainwindow_list_actions_method()
    calls = []

    class FakeContext:
        def list_actions(self, detailed=False):
            calls.append(detailed)
            return [{"name": "demo.action", "owner": "ctx"}]

    class ExplodingDispatcher:
        def list_actions(self, *args, **kwargs):
            raise AssertionError("GUI _list_actions should prefer ctx.list_actions")

    fake_window = SimpleNamespace(ctx=FakeContext(), dispatcher=ExplodingDispatcher())

    result = method(fake_window)

    assert result == [{"name": "demo.action", "owner": "ctx"}]
    assert calls == [True]
    assert "self.ctx.list_actions(detailed=True)" in source
    assert "self.ctx.action_dispatcher.list_actions" not in source


def test_gui_list_actions_fake_context_without_action_dispatcher_does_not_crash():
    method, _source = _load_gui_mainwindow_list_actions_method()
    fake_window = SimpleNamespace(
        ctx=SimpleNamespace(list_actions=lambda detailed=False: ["demo.action"]),
        dispatcher=None,
    )

    assert method(fake_window) == [{"name": "demo.action"}]


def test_cli_do_health_uses_context_standard_health_reader(capsys):
    calls = []

    class FakeContext:
        def get_system_health(self):
            calls.append("get_system_health")
            return {
                "status": "ok",
                "modules": {"demo": {"status": "OK"}},
                "system_uptime": 3,
            }

        @property
        def module_manager(self):
            raise AssertionError("CLI do_health must not touch context.module_manager")

    shell = SimpleNamespace(context=FakeContext())

    SanhuaCmdShell.do_health(shell, "")

    out = capsys.readouterr().out
    assert calls == ["get_system_health"]
    assert "系统健康状态: ok" in out
    assert "demo" in out


def test_cli_do_health_without_health_reader_degrades(capsys):
    shell = SimpleNamespace(context=SimpleNamespace())

    SanhuaCmdShell.do_health(shell, "")

    out = capsys.readouterr().out
    assert "系统健康状态: unknown" in out


def test_cli_do_list_uses_context_standard_loaded_modules_reader(capsys):
    calls = []

    class FakeContext:
        def get_loaded_modules(self):
            calls.append("get_loaded_modules")
            return ["alpha", "beta"]

        @property
        def module_manager(self):
            raise AssertionError("CLI do_list must not touch context.module_manager")

    shell = SimpleNamespace(context=FakeContext())

    SanhuaCmdShell.do_list(shell, "")

    out = capsys.readouterr().out
    assert calls == ["get_loaded_modules"]
    assert "已加载模块" in out
    assert "- alpha" in out
    assert "- beta" in out


def test_cli_do_list_without_loaded_modules_reader_degrades(capsys):
    shell = SimpleNamespace(context=SimpleNamespace())

    SanhuaCmdShell.do_list(shell, "")

    out = capsys.readouterr().out
    assert "当前无已加载模块" in out


def test_system_module_get_system_status_uses_context_standard_reader():
    calls = []

    class FakeContext:
        def get_system_status(self):
            calls.append("get_system_status")
            return {
                "status": "RUNNING",
                "system_running": True,
                "uptime": 5.0,
                "modules_loaded": 3,
            }

        @property
        def start_time(self):
            raise AssertionError("SystemModule.get_system_status must not touch context.start_time")

        @property
        def module_manager(self):
            raise AssertionError("SystemModule.get_system_status must not touch context.module_manager")

    module = SystemModule(SimpleNamespace(name="system"), FakeContext())

    result = module.get_system_status()

    assert calls == ["get_system_status"]
    assert result["status"] == "RUNNING"
    assert result["system_running"] is True
    assert result["modules_loaded"] == 3


def test_module_manager_start_modules_is_idempotent(monkeypatch, tmp_path):
    manager = _make_module_manager(monkeypatch, tmp_path)
    module = FakeLifecycleModule()
    manager.loaded_modules["reply_dispatcher"] = module

    manager.start_modules()
    manager.start_modules()

    assert module.start_count == 1
    assert module.post_start_count == 1
    assert len(FakeObserver.instances) == 1
    assert FakeObserver.instances[0].start_count == 1


def test_module_manager_stop_then_start_rebuilds_observer(monkeypatch, tmp_path):
    manager = _make_module_manager(monkeypatch, tmp_path)
    module = FakeLifecycleModule()
    manager.loaded_modules["reply_dispatcher"] = module

    manager.start_modules()
    first_observer = manager.observer
    manager.stop_modules()
    manager.stop_modules()
    manager.start_modules()
    second_observer = manager.observer

    assert module.start_count == 2
    assert module.stop_count == 1
    assert module.shutdown_count == 1
    assert first_observer is not second_observer
    assert first_observer.stop_count == 1
    assert first_observer.join_count == 1
    assert second_observer.start_count == 1
    assert all(observer.start_count == 1 for observer in FakeObserver.instances)


def test_reply_dispatcher_start_is_idempotent(monkeypatch):
    module = _make_reply_dispatcher(monkeypatch)

    module.start()
    first_thread = module._monitor_thread
    first_executor = module.thread_pool
    module.start()

    assert module._monitor_thread is first_thread
    assert module.thread_pool is first_executor
    assert first_thread.start_count == 1
    assert len(FakeReplyThread.instances) == 1
    assert len(FakeReplyExecutor.instances) == 1


def test_reply_dispatcher_stop_is_idempotent(monkeypatch):
    module = _make_reply_dispatcher(monkeypatch)

    module.start()
    first_thread = module._monitor_thread
    first_executor = module.thread_pool
    module.stop()
    module.stop()
    module.on_shutdown()

    assert first_thread.join_count == 1
    assert first_executor.shutdown_count == 1


def test_reply_dispatcher_stop_then_start_rebuilds_thread_and_executor(monkeypatch):
    module = _make_reply_dispatcher(monkeypatch)

    module.start()
    first_thread = module._monitor_thread
    first_executor = module.thread_pool
    module.stop()
    module.start()
    second_thread = module._monitor_thread
    second_executor = module.thread_pool
    module.handle_user_query({"text": "hello", "user": "tester"})

    assert second_thread is not first_thread
    assert second_executor is not first_executor
    assert first_thread.start_count == 1
    assert second_thread.start_count == 1
    assert first_executor._shutdown is True
    assert second_executor._shutdown is False
    assert second_executor.submit_count == 1
    assert all(thread.start_count == 1 for thread in FakeReplyThread.instances)


def test_reply_dispatcher_lifecycle_guard_source_is_explicit():
    source = (PROJECT_ROOT / "modules/reply_dispatcher/module.py").read_text(encoding="utf-8")

    assert "_started" in source
    assert "_ensure_thread_pool" in source
    assert "_ensure_monitor_thread" in source
    assert "_thread_pool_shutdown" in source
    assert "_monitor_thread_started" in source
    assert "self.thread_pool.shutdown" in source


def test_dispatch_action_is_compat_facade_to_call_action(monkeypatch):
    calls = []

    def fake_call_action(name, params=None, **kwargs):
        calls.append((name, params, kwargs))
        return {"ok": True, "name": name}

    monkeypatch.setattr(dispatcher, "call_action", fake_call_action)

    result = dispatcher.dispatch_action(
        "demo.action",
        params={"query": "hello"},
        trace_id="dispatch-governance",
    )

    assert result == {"ok": True, "name": "demo.action"}
    assert calls == [
        (
            "demo.action",
            {"query": "hello"},
            {"trace_id": "dispatch-governance"},
        )
    ]


def test_gui_health_short_circuit_uses_context_call_action(monkeypatch):
    ctx = _create_stubbed_context(monkeypatch)
    calls = []
    logs = []

    monkeypatch.setattr(
        chat_mod,
        "try_local_memory_answer",
        lambda *_args, **_kwargs: {"ok": False},
    )

    def action_caller(name, payload):
        calls.append((name, payload))
        return ctx.call_action(name, params=payload)

    orch = GUIChatOrchestrator(
        ctx=ctx,
        aicore=object(),
        action_caller=action_caller,
        list_actions=lambda: [],
        logger=logs.append,
        strip_protocol=lambda x: str(x or ""),
    )

    reply = orch.handle_chat("系统检测")

    assert calls == [("system.health_check", {})]
    assert "fake_module" in reply
    assert "baseline_e2e_stub" in reply
    assert any("system.health_check [sys_detect]" in line for line in logs)


def test_gui_memory_bridge_execute_uses_context_call_action_only():
    calls = []

    class FakeContext:
        def call_action(self, name, params=None, **kwargs):
            calls.append((name, params, kwargs))
            return {"ok": True, "source": "context.call_action"}

    class FakeAICore:
        context = FakeContext()

        @property
        def dispatcher(self):
            raise AssertionError("gui_memory_bridge.execute must not probe dispatcher fallback")

        @property
        def action_dispatcher(self):
            raise AssertionError("gui_memory_bridge.execute must not probe action_dispatcher fallback")

        @property
        def ACTION_MANAGER(self):
            raise AssertionError("gui_memory_bridge.execute must not probe ACTION_MANAGER fallback")

        @property
        def action_manager(self):
            raise AssertionError("gui_memory_bridge.execute must not probe action_manager fallback")

    result = gui_memory_bridge.execute(FakeAICore(), "memory.snapshot", limit=3)

    assert result == {"ok": True, "source": "context.call_action"}
    assert calls == [("memory.snapshot", {"limit": 3}, {})]


def test_gui_memory_bridge_execute_without_context_does_not_fallback_to_global_action_bus():
    class FakeAICore:
        @property
        def dispatcher(self):
            raise AssertionError("gui_memory_bridge.execute must not fallback to dispatcher")

        @property
        def action_dispatcher(self):
            raise AssertionError("gui_memory_bridge.execute must not fallback to action_dispatcher")

        @property
        def ACTION_MANAGER(self):
            raise AssertionError("gui_memory_bridge.execute must not fallback to ACTION_MANAGER")

        @property
        def action_manager(self):
            raise AssertionError("gui_memory_bridge.execute must not fallback to action_manager")

    result = gui_memory_bridge.execute(FakeAICore(), "memory.snapshot", limit=3)

    assert result == {}


def _load_memory_dock_with_fake_qt(monkeypatch):
    class FakeSignal:
        def connect(self, _callback):
            return None

    class FakeDockWidget:
        class DockWidgetFeature:
            DockWidgetMovable = 1
            DockWidgetFloatable = 2
            DockWidgetClosable = 4

        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def setFeatures(self, features):
            self.features = features

        def setWidget(self, widget):
            self.widget = widget

    class FakeWidget:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class FakeVBoxLayout:
        def __init__(self, widget):
            self.widget = widget
            self.widgets = []

        def addWidget(self, widget):
            self.widgets.append(widget)

    class FakeListWidget:
        def __init__(self):
            self.items = []

        def clear(self):
            self.items.clear()

        def addItem(self, item):
            self.items.append(item)

    class FakePushButton:
        def __init__(self, text):
            self.text = text
            self.clicked = FakeSignal()

    class FakeLabel:
        def __init__(self, text):
            self.text = text

        def setText(self, text):
            self.text = text

    class FakeFileDialog:
        save_path = ""
        open_path = ""

        @classmethod
        def getSaveFileName(cls, *args, **kwargs):
            return cls.save_path, "JSON Files (*.json)"

        @classmethod
        def getOpenFileName(cls, *args, **kwargs):
            return cls.open_path, "JSON Files (*.json)"

    class FakeMessageBox:
        info_calls = []
        critical_calls = []

        class StandardButton:
            Yes = 1

        @classmethod
        def question(cls, *args, **kwargs):
            return cls.StandardButton.Yes

        @classmethod
        def information(cls, *args, **kwargs):
            cls.info_calls.append((args, kwargs))

        @classmethod
        def critical(cls, *args, **kwargs):
            cls.critical_calls.append((args, kwargs))

    qtwidgets = types.ModuleType("PyQt6.QtWidgets")
    qtwidgets.QDockWidget = FakeDockWidget
    qtwidgets.QWidget = FakeWidget
    qtwidgets.QVBoxLayout = FakeVBoxLayout
    qtwidgets.QListWidget = FakeListWidget
    qtwidgets.QPushButton = FakePushButton
    qtwidgets.QLabel = FakeLabel
    qtwidgets.QFileDialog = FakeFileDialog
    qtwidgets.QMessageBox = FakeMessageBox

    pyqt6 = types.ModuleType("PyQt6")
    pyqt6.QtWidgets = qtwidgets

    monkeypatch.setitem(sys.modules, "PyQt6", pyqt6)
    monkeypatch.setitem(sys.modules, "PyQt6.QtWidgets", qtwidgets)

    module = importlib.import_module("core.gui.memory_dock")
    module = importlib.reload(module)
    return module, FakeFileDialog, FakeMessageBox


class _FakeMemoryContext:
    def __init__(self):
        self.calls = []

    def call_action(self, name, params=None, **kwargs):
        self.calls.append((name, params, kwargs))
        if name == "memory.snapshot":
            return {
                "ok": True,
                "data": {
                    "default": [
                        {"text": "hello memory", "category": "default"},
                    ]
                },
            }
        if name == "memory.add":
            return {"ok": True, "added": params}
        raise AssertionError(f"unexpected action: {name}")


def test_memory_dock_refresh_uses_memory_snapshot_action(monkeypatch):
    memory_dock, _file_dialog, _message_box = _load_memory_dock_with_fake_qt(monkeypatch)
    ctx = _FakeMemoryContext()

    dock = memory_dock.MemoryDock(ctx)
    ctx.calls.clear()

    dock.refresh()

    assert ctx.calls == [("memory.snapshot", {}, {})]
    assert dock.list.items == ["[default] hello memory"]


def test_memory_dock_export_json_uses_memory_snapshot_action(monkeypatch, tmp_path):
    memory_dock, file_dialog, _message_box = _load_memory_dock_with_fake_qt(monkeypatch)
    export_path = tmp_path / "memory.json"
    file_dialog.save_path = str(export_path)
    ctx = _FakeMemoryContext()
    dock = memory_dock.MemoryDock(ctx)
    ctx.calls.clear()

    dock.export_json()

    assert ctx.calls == [("memory.snapshot", {}, {})]
    exported = json.loads(export_path.read_text(encoding="utf-8"))
    assert exported["default"][0]["text"] == "hello memory"
    assert exported["default"][0]["category"] == "default"


def test_memory_dock_import_json_uses_memory_add_action(monkeypatch, tmp_path):
    memory_dock, file_dialog, _message_box = _load_memory_dock_with_fake_qt(monkeypatch)
    import_path = tmp_path / "memory_import.json"
    import_path.write_text(
        json.dumps({"notes": [{"text": "imported"}], "raw": "value"}, ensure_ascii=False),
        encoding="utf-8",
    )
    file_dialog.open_path = str(import_path)
    ctx = _FakeMemoryContext()
    dock = memory_dock.MemoryDock(ctx)
    ctx.calls.clear()

    dock.import_json()

    assert ctx.calls[:2] == [
        ("memory.add", {"text": "imported", "category": "notes"}, {}),
        ("memory.add", {"value": "value", "category": "raw"}, {}),
    ]
    assert ctx.calls[-1] == ("memory.snapshot", {}, {})


def test_memory_dock_clear_memory_is_controlled_skip_without_memory_action(monkeypatch):
    memory_dock, _file_dialog, message_box = _load_memory_dock_with_fake_qt(monkeypatch)
    ctx = _FakeMemoryContext()
    dock = memory_dock.MemoryDock(ctx)
    ctx.calls.clear()

    dock.clear_memory()

    assert ctx.calls == []
    assert message_box.info_calls
    assert "不支持" in dock.label.text


def test_execution_planner_action_step_uses_context_call_action_only():
    calls = []

    class FakeContext:
        def call_action(self, name, params=None):
            calls.append((name, params))
            return {"ok": True, "source": "context.call_action"}

    dispatcher_with_context = SimpleNamespace(context=FakeContext())
    step = PlanStep(
        step_id="step-1",
        title="demo action",
        kind="action",
        action_name="demo.action",
        params={"query": "hello"},
    )

    ok, payload = ExecutionPlanner()._execute_action_step(step, dispatcher_with_context, {})

    assert ok is True
    assert payload["bridge_method"] == "call_action(action_name, params=...)"
    assert payload["output"] == {"ok": True, "source": "context.call_action"}
    assert calls == [("demo.action", {"query": "hello"})]


def test_execution_planner_action_step_does_not_fallback_to_get_action_or_execute():
    class FakeDispatcher:
        def get_action(self, _name):
            raise AssertionError("execution_planner must not fallback to get_action(...).func")

        def execute(self, *_args, **_kwargs):
            raise AssertionError("execution_planner must not fallback to dispatcher.execute")

    step = PlanStep(
        step_id="step-2",
        title="demo action",
        kind="action",
        action_name="demo.action",
        params={"query": "hello"},
    )

    ok, payload = ExecutionPlanner()._execute_action_step(step, FakeDispatcher(), {})

    assert ok is False
    assert payload["status"] == "failed"
    assert payload["reason"] == "缺少标准 context.call_action 执行接口"
    assert payload["tried_methods"] == []
