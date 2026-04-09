import os
# 统一 base url（用你现有的 8080）
os.environ.setdefault("SANHUA_LLAMA_BASE_URL","http://127.0.0.1:8080/v1")

# 计算模型名（在 Python 里做 basename，避免 shell 嵌套引号）
default_model_path = os.path.expanduser("~/Desktop/聚核助手2.0/models/llama3-8b/llama3-8b.gguf")
model_path = os.environ.get("SANHUA_MODEL", default_model_path)
model_name = os.environ.get("SANHUA_ACTIVE_MODEL", os.path.basename(model_path))

# import 即注册 ai.* 动作
import core.core2_0.sanhuatongyu.services.model_engine.register_actions_llamacpp  # noqa

# 兼容补丁（list_local_models / use_llamacpp_http / chat_llamacpp）
from core.core2_0.sanhuatongyu.services.model_engine.engine_compat import install
install()

from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER as D

print("🔗 use:",  D.execute("ai.use_llamacpp"))
print("🧠 set:",  D.execute("ai.set_model", params={"name": model_name}))

actions = list(D._actions.keys()) if hasattr(D,"_actions") else (D.list_actions() or [])
print("📋 actions(<=50):", actions[:50])
print("ai.chat 可用：", "ai.chat" in actions)

print("💬 chat:", D.execute("ai.chat", params={
    "text":"ping",
    "system":"你是三花聚顶·聚核助手"
}))
