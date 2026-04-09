
# core/core2_0/sanhuatongyu/services/model_engine/engine_compat.py
# 侧挂式兼容层：补齐 list_local_models / select_model，并提供 llama.cpp HTTP 直连

import os, json, glob, urllib.request

def _post_json(url, payload, timeout=120):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def install():
    from .engine import ModelEngine

    # --- 1) 缺啥补啥：list_local_models ---
    if not hasattr(ModelEngine, "list_local_models"):
        def list_local_models(self, models_dir=None):
            models_dir = models_dir or os.path.join(os.getcwd(), "models")
            ggufs = glob.glob(os.path.join(models_dir, "**", "*.gguf"), recursive=True)
            return [{"id":p, "name":os.path.basename(p)} for p in ggufs]
        ModelEngine.list_local_models = list_local_models

    # --- 2) 缺啥补啥：select_model ---
    if not hasattr(ModelEngine, "select_model"):
        def select_model(self, model):
            # 接受文件全路径或 basename
            if os.path.isfile(model):
                self._current_model = model
            else:
                # 尝试在 models 目录匹配
                models = ModelEngine.list_local_models(self)
                cand = [m["id"] for m in models if os.path.basename(m["id"]) == model]
                self._current_model = cand[0] if cand else model
            return self._current_model
        ModelEngine.select_model = select_model

    # --- 3) 轻量 llama.cpp HTTP 适配 ---
    if not hasattr(ModelEngine, "use_llamacpp_http"):
        def use_llamacpp_http(self, base_url=None, model=None):
            self._llama_base = base_url or os.environ.get("SANHUA_LLAMA_BASE_URL", "http://127.0.0.1:8080/v1")
            # 优先显式传入，其次 SANHUA_ACTIVE_MODEL，再次从 SANHUA_MODEL 推断文件名
            self._llama_model = (
                model
                or os.environ.get("SANHUA_ACTIVE_MODEL")
                or os.path.basename(os.environ.get("SANHUA_MODEL",""))  # e.g. llama3-8b.gguf
            )
            if not self._llama_model:
                # 兜底用当前引擎选择的模型
                self._llama_model = getattr(self, "_current_model", None)
                if isinstance(self._llama_model, str):
                    self._llama_model = os.path.basename(self._llama_model)
            return True
        ModelEngine.use_llamacpp_http = use_llamacpp_http

    if not hasattr(ModelEngine, "chat_llamacpp"):
        def chat_llamacpp(self, prompt, system=None, temperature=0.7, max_tokens=512, **kwargs):
            base = getattr(self, "_llama_base", None)
            model = getattr(self, "_llama_model", None)
            if not base or not model:
                raise RuntimeError("llamacpp http 未配置，先调用 use_llamacpp_http()")
            url = base.rstrip("/") + "/chat/completions"
            msgs = []
            if system:
                msgs.append({"role":"system","content":system})
            msgs.append({"role":"user","content":prompt})
            body = {
                "model": model,
                "messages": msgs,
                "temperature": float(temperature),
                "max_tokens": int(max_tokens)
            }
            out = _post_json(url, body)
            return out["choices"][0]["message"]["content"]
        ModelEngine.chat_llamacpp = chat_llamacpp
