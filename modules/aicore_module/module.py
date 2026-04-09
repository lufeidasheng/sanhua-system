import inspect

from core.core2_0.sanhuatongyu.module.base import BaseModule
from core.aicore.aicore import get_aicore_instance
from core.core2_0.sanhuatongyu.logger import get_logger
from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER

logger = get_logger("aicore_module")

class AICoreModule(BaseModule):
    """
    三花聚顶AICore模块（全局标准/热插拔版）
    - 支持全局兼容动作注册（aicore.chat）
    - 支持事件总线订阅/响应
    - 自动集成 AICore 实例和提示词中心
    """
    def __init__(self, meta=None, context=None):
        super().__init__(meta, context)
        self.aicore = get_aicore_instance()  # 全局AICore实例
        self._actions_registered = False
        self._compat_chat_depth = 0

    def preload(self):
        logger.info("AICore模块 preload 开始")
        self._register_actions()
        logger.info("AICore模块 preload 结束")

    def setup(self):
        logger.info("AICore模块 setup 开始")
        self._register_actions()
        if hasattr(self, "context") and self.context is not None:
            self.context.aicore = self.aicore
            if hasattr(self.context, "event_bus") and self.context.event_bus:
                self.context.event_bus.subscribe("aicore.chat", self.handle_event)
        logger.info("AICore模块 setup 结束")

    def start(self):
        logger.info("AICore模块启动完成")

    def stop(self):
        logger.info("AICore模块停止，准备关闭AICore")
        self.aicore.shutdown()

    def health_check(self) -> dict:
        aicore = getattr(self, "aicore", None)
        if aicore is None:
            return {
                "status": "ERROR",
                "module": getattr(self.meta, "name", "aicore_module"),
                "reason": "aicore_instance_missing",
            }

        status = "WARNING"
        reason = "status_unavailable"
        detail = None
        try:
            fn = getattr(aicore, "get_status", None)
            if callable(fn):
                detail = fn()
                if isinstance(detail, dict):
                    status = str(detail.get("status") or "").strip().upper() or "WARNING"
                    reason = ""
                    if status in ("WARNING", "UNKNOWN"):
                        healthy_flags = []
                        backend = detail.get("backend_status", {})
                        env_backend = backend.get("env_backend", {}) if isinstance(backend, dict) else {}
                        if isinstance(env_backend, dict):
                            if "is_active" in env_backend:
                                healthy_flags.append(bool(env_backend.get("is_active")))
                            if "healthy" in env_backend:
                                healthy_flags.append(bool(env_backend.get("healthy")))
                        for key in ("runtime_model_truth", "memory_health"):
                            block = detail.get(key, {})
                            if isinstance(block, dict) and "ok" in block:
                                healthy_flags.append(bool(block.get("ok")))
                        overload = detail.get("overload", {})
                        if isinstance(overload, dict) and "is_overloaded" in overload:
                            healthy_flags.append(not bool(overload.get("is_overloaded")))
                        if healthy_flags and all(healthy_flags):
                            status = "OK"
                else:
                    status = "WARNING"
                    reason = "status_not_dict"
        except Exception as e:
            status = "ERROR"
            reason = f"status_error:{e}"

        return {
            "status": status,
            "module": getattr(self.meta, "name", "aicore_module"),
            "reason": reason,
            "detail": detail,
        }

    def handle_event(self, event_name, data=None):
        logger.info(f"收到事件: {event_name} data={data}")
        if event_name == "aicore.chat":
            query = (data or {}).get("query", "")
            try:
                resp = self._call_compat_chat(query)
            except Exception as e:
                resp = f"AI出错: {e}"
            if hasattr(self.context, "event_bus") and self.context.event_bus:
                self.context.event_bus.publish(
                    "aicore.chat_response",
                    {"query": query, "response": resp}
                )
            return resp
        return None

    def chat(self, context, params=None, **kwargs):
        """
        对外兼容/兜底桥接口
        - context: 系统主控上下文（自动注入）
        - params: 兼容 GUI/CLI {"query": str}
        - kwargs: 兼容CLI/GUI的 query
        """
        try:
            if params and isinstance(params, dict):
                query = params.get("query", "")
            else:
                query = kwargs.get("query", "")
            logger.info(f"[aicore_module] chat 被调用: query={query}")
            return self._call_compat_chat(query)
        except Exception as e:
            logger.error(f"[aicore_module] chat 出错: {e}")
            return f"AI出错: {e}"

    def _call_compat_chat(self, query: str):
        query = str(query or "")

        if self._compat_chat_depth > 0:
            logger.warning("[aicore_module] compat chat recursion blocked")
            return "AI出错: aicore_chat_recursion_blocked"

        class_chat = getattr(type(self.aicore), "chat", None)
        raw_chat = inspect.unwrap(class_chat) if callable(class_chat) else None
        if not callable(raw_chat):
            raise RuntimeError("aicore_raw_chat_unavailable")

        self._compat_chat_depth += 1
        try:
            return raw_chat(self.aicore, query)
        finally:
            self._compat_chat_depth = max(0, self._compat_chat_depth - 1)

    def _register_actions(self):
        if not self._actions_registered:
            # 避免重复注册
            already = [a["name"] for a in ACTION_MANAGER.list_actions(detailed=True)]
            if "aicore.chat" not in already:
                # aicore.chat 仅保留为兼容/兜底桥，不作为正式主聊天桥
                ACTION_MANAGER.register_action(
                    name="aicore.chat",
                    func=lambda context, params=None, **kwargs: self.chat(context, params, **kwargs),
                    description="AICore 兼容/兜底对话桥",
                    permission="user",
                    module="aicore_module"
                )
                logger.info("注册兼容兜底桥动作: aicore.chat")
            else:
                logger.info("aicore.chat 已注册，跳过")
            self._actions_registered = True

    def cleanup(self):
        ACTION_MANAGER.unregister_action("aicore.chat")
        logger.info("aicore.chat 动作反注册完成")

# ==== 自动注册函数（可选，兼容脚手架工具/热插拔）====
def register_actions(dispatcher, context=None):
    """
    注册 aicore.chat 到全局 QuantumActionDispatcher（兼容/兜底桥）
    """
    mod = AICoreModule(meta=dispatcher.get_module_meta("aicore_module"), context=context)
    dispatcher.register_action(
        "aicore.chat",
        func=lambda ctx, params=None, **kwargs: mod.chat(ctx, params, **kwargs),
        description="AICore 兼容/兜底对话桥",
        module="aicore_module"
    )
    logger.info("register_actions: aicore.chat 兼容兜底桥注册完成")
