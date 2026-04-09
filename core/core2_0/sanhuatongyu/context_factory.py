"""
三花聚顶 · context_factory.py
统一系统上下文创建工厂，支持 CLI/GUI/API/Voice/Script/Service 等所有入口调用。
所有入口都通过此工厂获得唯一主控上下文 SystemContext。
作者: 三花聚顶开发团队
"""

from __future__ import annotations

import os
from typing import Optional
from .context import SystemContext

# ==== 路径配置（适配所有入口）====
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DEFAULT_GLOBAL_CONFIG = os.path.normpath(os.path.join(BASE_DIR, "../../../config/global.yaml"))
DEFAULT_USER_CONFIG   = os.path.normpath(os.path.join(BASE_DIR, "../../../config/user.yaml"))
DEFAULT_DEV_MODE = False


def _guess_project_root() -> str:
    """
    BASE_DIR: core/core2_0/sanhuatongyu/xxx
    project_root: ../../../  -> 项目根目录（包含 modules/ config/）
    """
    return os.path.normpath(os.path.join(BASE_DIR, "../../../"))


def _ensure_module_manager(context: SystemContext, entry_mode: str, log) -> None:
    """
    挂载 module_manager，并完成扫描/加载/启动（可降级）。
    注意：为了避免“双启动”，这里将 context.system_running 先置为 False，
    让 ModuleManager.load_single_module 不在加载期调用 start()，
    再统一调用 start_modules()。
    """
    project_root = _guess_project_root()
    modules_dir = os.path.join(project_root, "modules")
    log.info("【context_factory】modules_dir=%s", modules_dir)

    if not os.path.isdir(modules_dir):
        log.warning("【context_factory】未发现 modules 目录，跳过模块系统挂载: %s", modules_dir)
        context.module_manager = None
        return

    try:
        from core.core2_0.sanhuatongyu.module.manager import ModuleManager  # 按你的路径
    except Exception as e:
        log.error("【context_factory】导入 ModuleManager 失败，跳过模块系统: %s", e)
        context.module_manager = None
        return

    try:
        # 避免双启动：加载期不自动 start
        try:
            context.system_running = False
        except Exception:
            pass

        mm = ModuleManager(modules_dir, context)
        context.module_manager = mm

        # 1) 扫描 metadata
        mm.load_modules_metadata()
        log.info("【context_factory】模块元数据扫描完成：modules=%d", len(getattr(mm, "modules", {}) or {}))

        # 2) 按入口加载
        mm.load_modules(entry_point=entry_mode)
        log.info("【context_factory】模块加载完成：loaded=%d", len(getattr(mm, "loaded_modules", {}) or {}))

        # 3) 标记系统运行，并统一启动
        try:
            context.system_running = True
        except Exception:
            pass
        mm.start_modules()
        log.info("【context_factory】模块启动完成（含热加载监听）")
        log.info("【context_factory】module_manager挂载=%s loaded_modules=%d",
                 bool(context.module_manager), len(getattr(mm, "loaded_modules", {}) or {}))

    except Exception as e:
        log.error("【context_factory】module_manager 初始化/加载失败：%s", e)
        context.module_manager = None
        # 不抛出，保证系统可降级启动


def create_system_context(
    global_config_path: Optional[str] = None,
    user_config_path: Optional[str] = None,
    dev_mode: Optional[bool] = None,
    entry_mode: str = "cli",
) -> SystemContext:
    """
    三花聚顶 · 统一主控上下文工厂
    所有入口（CLI/GUI/Voice/API...）都应通过本工厂获得唯一 SystemContext 实例。
    """
    import logging
    log = logging.getLogger("context_factory")
    log.info("【context_factory】初始化参数: global=%s, user=%s, dev=%s, entry=%s",
             global_config_path, user_config_path, dev_mode, entry_mode)

    # 1. 归一参数
    global_config_path = global_config_path or DEFAULT_GLOBAL_CONFIG
    user_config_path = user_config_path or DEFAULT_USER_CONFIG
    dev_mode = dev_mode if dev_mode is not None else DEFAULT_DEV_MODE

    log.info("【context_factory】最终参数: global=%s, user=%s, dev=%s, entry=%s",
             global_config_path, user_config_path, dev_mode, entry_mode)

    # 2. 构建主控上下文
    context = SystemContext(
        global_config_path=global_config_path,
        user_config_path=user_config_path,
        dev_mode=dev_mode
    )
    context.entry_mode = entry_mode

    # 3. 统一挂载 QuantumActionDispatcher 单例
    from core.core2_0.sanhuatongyu.action_dispatcher import dispatcher as ACTION_DISPATCHER

    if getattr(context, "action_dispatcher", None) not in (None, ACTION_DISPATCHER):
        log.warning("【context_factory】注意：原 context.action_dispatcher 已存在且非全局单例，已强制替换！")
    context.action_dispatcher = ACTION_DISPATCHER

    log.info("【context_factory】ACTION_DISPATCHER id=%s, context.action_dispatcher id=%s",
             id(ACTION_DISPATCHER), id(context.action_dispatcher))

    # 3.5 关键：挂载模块系统（否则 GUI 模块管理必然为空）
    _ensure_module_manager(context, entry_mode, log)

    # 4. 健康检查动作自动注册（只注册一次，防止多入口冲突）
    actions_now = ACTION_DISPATCHER.list_actions()
    log.info("【context_factory】当前已注册动作: %s", actions_now)

    force_health = entry_mode == "gui"
    if force_health or "system.health_check" not in actions_now:
        if force_health:
            log.info("【context_factory】GUI entry: 强制覆盖 system.health_check")
        else:
            log.info("【context_factory】未检测到 system.health_check，尝试自动注册。")

        def default_system_health(*args, **kwargs):
            if getattr(context, "module_manager", None):
                try:
                    result = context.module_manager.health_check()
                    modules_count = len((result or {}).get("modules") or {})
                    log.info("【context_factory】system.health_check modules=%d", modules_count)
                    return result
                except Exception as e:
                    log.error("【context_factory】health_check 调用失败：%s", e)
                    return {"status": "error", "error": str(e), "modules": {}}
            log.warning("【context_factory】module_manager 不可用，返回未知状态。")
            return {"status": "unknown", "modules": {}}

        ACTION_DISPATCHER.register_action(
            name="system.health_check",
            func=default_system_health,
            module="system",
            description="系统健康检查（自动注入）",
            permission="system"
        )
        log.info("【context_factory】system.health_check 已注册到 ACTION_DISPATCHER")
    else:
        log.info("【context_factory】system.health_check 已存在，无需重复注册")

    # 5. 注入标准分发口 call_action，彻底解耦各入口/模块
    if not hasattr(context, "call_action"):

        def call_action(name: str, *args, **kwargs):
            log.info("【context_factory】call_action: %s, args=%s, kwargs=%s", name, args, kwargs)
            return context.action_dispatcher.execute(name, *args, **kwargs)

        context.call_action = call_action
        log.info("【context_factory】call_action 已绑定到 context")

    log.info("【context_factory】create_system_context 全流程完毕，SystemContext Ready!")
    return context


__all__ = ["create_system_context"]
