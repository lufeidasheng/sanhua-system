# tools/sanhua_smoke_check.py
# -*- coding: utf-8 -*-
import os, sys, json, traceback, types

ROOT = os.getcwd()
sys.path.insert(0, ROOT)

R = []  # 结果收集

def ok(name, detail=""):
    R.append(("✅", name, detail))

def warn(name, detail=""):
    R.append(("⚠️", name, detail))

def bad(name, detail=""):
    R.append(("❌", name, detail))

def header(t): 
    print("\n" + "="*8 + " " + t + " " + "="*8)

def try_call(obj, names, *a, **k):
    for n in names:
        if hasattr(obj, n):
            f = getattr(obj, n)
            try:
                return n, f(*a, **k)
            except Exception:
                raise
    raise AttributeError(f"none of methods {names} on {obj}")

def main():
    header("路径/环境")
    print("ROOT:", ROOT)
    if not os.path.isdir(ROOT):
        bad("路径错误", ROOT); return

    # 1) Dispatcher
    header("Action Dispatcher")
    dispatcher = None
    try:
        from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER as dispatcher
        ok("导入 ACTION_MANAGER", "core/core2_0/.../action_dispatcher.py")
    except Exception as e1:
        try:
            from core.core2_0.sanhuatongyu.action_dispatcher import dispatcher as dispatcher
            warn("导入 dispatcher(兼容名)", str(e1))
        except Exception as e2:
            bad("导入调度器失败", f"{e1}\n{e2}")
            dispatcher = None

    # 1.1 注册&执行自测
    if dispatcher:
        try:
            def _selftest_ping(params=None):
                return {"pong": True, "params": params or {}}
            if hasattr(dispatcher, "register_action"):
                dispatcher.register_action("selftest.ping", _selftest_ping, description="ping")
                ok("register_action", "selftest.ping")
            else:
                warn("缺少 register_action", "请在 dispatcher 暴露 register_action(name, handler, ...)")
            # execute 变体适配
            try:
                mname, res = try_call(dispatcher, ("execute","call","invoke","run_action"), "selftest.ping", params={"x":1})
                ok(f"{mname} 调用动作", json.dumps(res, ensure_ascii=False))
            except Exception as e:
                warn("调用动作失败", repr(e))
        except Exception as e:
            bad("Dispatcher 自测异常", repr(e))

    # 2) Context & ModuleManager
    header("System Context & ModuleManager")
    ctx = None
    try:
        from core.core2_0.sanhuatongyu.context_factory import create_system_context
        ctx = create_system_context(entry_mode="gui")
        ok("create_system_context", "entry_mode=gui")
        if hasattr(ctx, "action_dispatcher"):
            ok("context.action_dispatcher", "存在")
        else:
            warn("context.action_dispatcher", "缺失")
        # ModuleManager
        try:
            from core.core2_0.sanhuatongyu.module.manager import ModuleManager
            mods_dir = ctx.get_config("modules_dir","modules") if hasattr(ctx,"get_config") else "modules"
            mm = ModuleManager(mods_dir, ctx)
            ok("ModuleManager 可实例化", mods_dir)
        except Exception as e:
            warn("ModuleManager 导入/实例化失败", repr(e))
    except Exception as e:
        bad("create_system_context 失败", repr(e))

    # 3) ModelEngine 3.1
    header("ModelEngine 3.1")
    try:
        from core.core2_0.sanhuatongyu.services.model_engine.engine import ModelEngine
        me = ModelEngine(meta=None, context=ctx)
        ok("ModelEngine 导入/实例化", "engine.ModelEngine")
        # 后端注册能力存在性检查
        for attr in ("register_backend","use","list_local_models","select_model","chat"):
            if hasattr(me, attr):
                ok(f"ModelEngine.{attr}", "存在")
            else:
                warn(f"ModelEngine.{attr}", "缺失")
    except Exception as e:
        bad("ModelEngine 失败", repr(e))

    # 4) AICore & Memory
    header("AICore & Memory")
    ac = None
    try:
        from core.aicore.aicore import get_aicore_instance
        ac = get_aicore_instance()
        ok("AICore 单例", "get_aicore_instance()")
        # memory_manager / memory_engine
        if hasattr(ac, "memory_manager"):
            ok("AICore.memory_manager", "存在")
        elif hasattr(ac, "memory_engine"):
            warn("AICore.memory_manager", "未发现，fallback=memory_engine")
        else:
            warn("AICore 记忆", "未发现 memory_manager/memory_engine")

        # chat() 快速冒烟 —— 暂时短路模型调用，避免阻塞
        if hasattr(ac, "model_engine") and hasattr(ac.model_engine, "chat"):
            old_chat = ac.model_engine.chat
            try:
                ac.model_engine.chat = lambda *a, **k: "SELFTEST_OK"
                out = ac.chat("hello")
                ok("AICore.chat", f"输出: {str(out)[:48]}")
            except Exception as e:
                warn("AICore.chat 异常", repr(e))
            finally:
                ac.model_engine.chat = old_chat
        else:
            warn("AICore.model_engine.chat", "缺失，未测 chat()")
    except Exception as e:
        warn("AICore 导入失败", repr(e))

    # 5) PromptMemoryBridge & MemoryManager
    try:
        from core.prompt_engine.prompt_memory_bridge import PromptMemoryBridge
        ok("PromptMemoryBridge 导入", "")
    except Exception as e:
        warn("PromptMemoryBridge 导入失败", repr(e))
    try:
        from core.memory_engine.memory_manager import MemoryManager
        mm = MemoryManager()
        ok("MemoryManager 导入/实例化", "")
    except Exception as e:
        warn("MemoryManager 导入失败", repr(e))

    # 6) MemoryDock（GUI 侧挂件）
    try:
        from core.gui.memory_dock import MemoryDock
        ok("MemoryDock 导入", "")
    except Exception as e:
        warn("MemoryDock 导入失败", repr(e))

    # 7) alias loader
    try:
        from utils.alias_loader import load_aliases_from_yaml
        p = os.path.join(ROOT, "config/aliases.yaml")
        if os.path.exists(p):
            try:
                cnt = load_aliases_from_yaml(p, dispatcher if dispatcher else None)
                ok("load_aliases_from_yaml", f"{cnt} 条")
            except Exception as e:
                warn("alias 加载异常", repr(e))
        else:
            warn("aliases.yaml 未找到", p)
    except Exception as e:
        warn("alias loader 导入失败", repr(e))

    # 总结
    header("总结")
    for flag, name, detail in R:
        if detail:
            print(flag, name, "-", detail)
        else:
            print(flag, name)

if __name__ == "__main__":
    main()
