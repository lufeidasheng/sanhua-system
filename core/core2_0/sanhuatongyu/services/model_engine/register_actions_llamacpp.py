# -*- coding: utf-8 -*-
"""
三花聚顶 · llama.cpp HTTP 动作注册（server-first / protocol-safe / hardened）
- AICore/Python 侧只做 client，不负责切换 gguf 权重
  - 真正换权重：run_gui.sh 重新选择并重启 llama-server（-m xxx.gguf）
- 动作：
  - ai.use_llamacpp(base_url?)                 → 绑定 HTTP 端点，探测 server 实际加载模型
  - ai.set_model(name_or_path)                 → 软选择（仅记录/展示），不改 server 权重
  - ai.chat(text, system?, temperature?, max_tokens?) → 走 /v1/chat/completions
  - ai.ask（macOS 可选）→ 弹窗输入后转 ai.chat
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import urllib.request
import urllib.error
from typing import Any, Dict, Optional, Tuple

from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER as dispatcher
from core.core2_0.sanhuatongyu.logger import get_logger
from core.core2_0.sanhuatongyu.services.model_engine.engine import ModelEngine
from core.core2_0.sanhuatongyu.services.model_engine.engine_compat import install as compat_install

logger = get_logger("model_engine.register_actions_llamacpp")

# ===================== 全局状态（线程安全） =====================

_LOCK = threading.RLock()
_ME: Optional[ModelEngine] = None
_BASE_V1: Optional[str] = None          # 规范化后的 .../v1
_SOFT_MODEL: Optional[str] = None       # 软选择（展示用）
_SERVER_MODEL: Optional[str] = None     # server /v1/models 探测到的
_LAST_PROBE_TS: float = 0.0             # 探测节流
_PROBE_TTL_SEC: float = float(os.environ.get("SANHUA_LLAMA_PROBE_TTL", "3") or "3")
_ACTIONS_REGISTERED = False


# ===================== 协议清洗（关键：先提取 final，再清洗） =====================

_FINAL_PATTERNS = [
    # 你现在遇到的：assistantfinal...（可能同一行，也可能换行）
    re.compile(r"assistantfinal\s*[:：]?\s*(.+)$", re.I | re.S),
    # 常见：final ...
    re.compile(r"(?m)^\s*final\s*[:：]\s*(.+)$", re.I | re.S),
    # 某些模型会输出：final\nxxx
    re.compile(r"(?m)^\s*final\s*$\s*(.+)$", re.I | re.S),
    # 退一步：assistant: xxx （避免抓到 system/user，放后面）
    re.compile(r"(?m)^\s*assistant\s*[:：]\s*(.+)$", re.I | re.S),
]

def _extract_final_answer(raw: str) -> str:
    """
    优先从明显的“最终答案段”里提取，避免把 analysis/中间过程喂给 TTS。
    这是你当前“assistantfinal 被念出来”的根治点。
    """
    s = (raw or "").strip()
    if not s:
        return ""

    for rx in _FINAL_PATTERNS:
        m = rx.search(s)
        if m:
            ans = (m.group(1) or "").strip()
            if ans:
                return ans

    # 兜底：如果包含“assistantfinal”但没匹配到（极端换行/乱码），从其后截断
    low = s.lower()
    idx = low.find("assistantfinal")
    if idx >= 0:
        tail = s[idx + len("assistantfinal"):].lstrip(":： \n\r\t")
        if tail.strip():
            return tail.strip()

    return s


def _strip_llm_protocol(text: Any) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)

    # 0) 先提取最终答案段（最重要）
    t = _extract_final_answer(text)
    if not t:
        return ""

    # 1) 去 think/analysis/reasoning 块（强力）
    t = re.sub(r"<\s*think\s*>.*?<\s*/\s*think\s*>", "", t, flags=re.I | re.S)
    t = re.sub(r"<\s*analysis\s*>.*?<\s*/\s*analysis\s*>", "", t, flags=re.I | re.S)
    t = re.sub(r"<\s*reasoning\s*>.*?<\s*/\s*reasoning\s*>", "", t, flags=re.I | re.S)
    t = re.sub(r"<\s*thinking\s*>.*?<\s*/\s*thinking\s*>", "", t, flags=re.I | re.S)

    # 2) 去 ChatML / channel token
    for pat in [
        r"<\s*\|\s*channel\s*\|\s*>",
        r"<\s*\|\s*message\s*\|\s*>",
        r"<\s*\|\s*start\s*\|\s*>",
        r"<\s*\|\s*end\s*\|\s*>",
        r"<\s*\|\s*im_start\s*\|\s*>",
        r"<\s*\|\s*im_end\s*\|\s*>",
        r"<\|\s*.*?\s*\|>",
    ]:
        t = re.sub(pat, "", t, flags=re.I)

    # 3) 去开头残留 "analysis" / "assistantfinal"
    t = re.sub(r"^\s*analysis\s*", "", t, flags=re.I)
    t = re.sub(r"^\s*assistantfinal\s*", "", t, flags=re.I)

    # 4) 去残余标签
    t = re.sub(r"<\s*[^>]*\s*>", "", t)

    # 5) 收敛空白
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = t.strip()

    return t


# ===================== 通用返回格式 =====================

def _ok(data: Any = None, **extra) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": True}
    if data is not None:
        out["data"] = data
    out.update(extra)
    return out

def _err(msg: Any, **extra) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": False, "error": str(msg)}
    out.update(extra)
    return out


# ===================== URL / ENV 规范化 =====================

def _normalize_base_v1(base: str) -> str:
    base = (base or "").strip()
    if not base:
        base = "http://127.0.0.1:8080"
    base = base.rstrip("/")
    if base.endswith("/v1"):
        return base
    return base + "/v1"

def _get_base_v1_from_params(p: Dict[str, Any]) -> str:
    base = (
        p.get("base_url")
        or os.environ.get("SANHUA_LLAMA_BASE_URL")
        or os.environ.get("SANHUA_LLAMACPP_BASE_URL")
        or "http://127.0.0.1:8080"
    )
    return _normalize_base_v1(str(base))


# ===================== HTTP 探测：/v1/models =====================

def _http_get_json(url: str, timeout: float = 6.0) -> Dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        raise RuntimeError(f"HTTP {e.code}: {body[:500]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"连接失败: {e}")

def _parse_models_payload(obj: Dict[str, Any]) -> Tuple[Optional[str], Optional[list]]:
    data = obj.get("data")
    if isinstance(data, list):
        if data:
            m0 = data[0]
            if isinstance(m0, dict):
                mid = (m0.get("id") or m0.get("name") or "").strip() or None
                return mid, data
            return str(m0).strip() or None, data
        return None, data

    models = obj.get("models")
    if isinstance(models, list):
        if models:
            m0 = models[0]
            if isinstance(m0, dict):
                mid = (m0.get("id") or m0.get("name") or "").strip() or None
                return mid, models
            return str(m0).strip() or None, models
        return None, models

    return None, None

def _probe_server_models(base_v1: str, force: bool = False) -> Dict[str, Any]:
    global _SERVER_MODEL, _LAST_PROBE_TS

    now = time.time()
    if (not force) and (_SERVER_MODEL is not None) and (now - _LAST_PROBE_TS < _PROBE_TTL_SEC):
        return {"server_model": _SERVER_MODEL, "cached": True}

    obj = _http_get_json(f"{base_v1}/models", timeout=5.0)
    mid, lst = _parse_models_payload(obj)
    _SERVER_MODEL = mid
    _LAST_PROBE_TS = now
    return {"server_model": _SERVER_MODEL, "cached": False, "raw_count": (len(lst) if isinstance(lst, list) else None)}


# ===================== ModelEngine 初始化（低侵入 + 自愈） =====================

def _ensure_engine(base_v1: str) -> None:
    global _ME, _BASE_V1

    if _ME is None:
        compat_install()
        _ME = ModelEngine(meta=None, context=None)

    if _BASE_V1 != base_v1:
        _BASE_V1 = base_v1
        try:
            _ME.use_llamacpp_http(base_url=base_v1, model=None)
        except TypeError:
            _ME.use_llamacpp_http()


# ===================== 动作实现 =====================

def ai_use_llamacpp(params=None, **kw):
    p = {**(params or {}), **kw}
    base_v1 = _get_base_v1_from_params(p)

    with _LOCK:
        try:
            _ensure_engine(base_v1)
        except Exception as e:
            return _err(e, base_url_v1=base_v1)

        probe = {}
        try:
            probe = _probe_server_models(base_v1, force=bool(p.get("force_probe")))
        except Exception as e:
            logger.warning(f"⚠️ /v1/models 探测失败（不阻塞）：{e}")
            probe = {"server_model": None, "error": str(e)}

        global _SOFT_MODEL
        env_active = (os.environ.get("SANHUA_ACTIVE_MODEL") or "").strip()
        _SOFT_MODEL = env_active or (probe.get("server_model") or "") or _SOFT_MODEL

        return _ok({
            "base_url_v1": _BASE_V1,
            "server_model": probe.get("server_model"),
            "soft_model": _SOFT_MODEL,
            "note": "server-first: 权重由 llama-server -m 决定；Python 侧不切换 gguf",
            **probe
        })


def ai_set_model(params=None, **kw):
    p = {**(params or {}), **kw}
    name = (p.get("name") or p.get("model") or p.get("path") or "").strip()
    if not name:
        return _err("missing name/model/path")

    with _LOCK:
        global _SOFT_MODEL
        _SOFT_MODEL = os.path.basename(name)
        os.environ["SANHUA_ACTIVE_MODEL"] = _SOFT_MODEL

        return _ok({
            "soft_model": _SOFT_MODEL,
            "note": "server-first: 软选择不切换权重；换 gguf 请重启 run_gui.sh"
        })


def ai_chat(params=None, **kw):
    p = {**(params or {}), **kw}
    text = (p.get("text") or p.get("prompt") or p.get("query") or "").strip()
    if not text:
        return _err("missing text/prompt")

    sysmsg = (p.get("system") or "").strip()
    if not sysmsg:
        sysmsg = (
            "你是三花聚顶·聚核助手。请严格遵守以下输出规则："
            "1) 只用中文回答；2) 直接给最终答案；3) 不要输出思考过程；"
            "4) 不要包含任何协议标记（如 <|...|>、<think> 等）；5) 纯文本输出。"
        )

    temp = float(p.get("temperature", 0.7))
    mx = int(p.get("max_tokens", 512))
    base_v1 = _get_base_v1_from_params(p)

    with _LOCK:
        try:
            _ensure_engine(base_v1)
        except Exception as e:
            return _err(e, hint="模型引擎初始化失败：请确认 llama-server 已启动", base_url_v1=base_v1)

        model_for_api = (
            _SOFT_MODEL
            or (os.environ.get("SANHUA_ACTIVE_MODEL") or "").strip()
            or (_SERVER_MODEL or "loaded")
        )

        try:
            try:
                out = _ME.chat_llamacpp(
                    text,
                    system=sysmsg,
                    temperature=temp,
                    max_tokens=mx,
                    model=model_for_api,
                )
            except TypeError:
                out = _ME.chat_llamacpp(text, system=sysmsg, temperature=temp, max_tokens=mx)
        except Exception as e:
            return _err(e, hint="请确认 /v1/chat/completions 可用，或检查 /tmp/llama_server.log")

        clean = _strip_llm_protocol(out)
        # 二次兜底：还敢冒头就再清一次
        if "assistantfinal" in clean.lower() or "<|" in clean or clean.lower().startswith("analysis"):
            clean = _strip_llm_protocol(clean)

        # 只返回 reply，别把 meta 带给 TTS（你的 tts.speak 只拿 text）
        return _ok({"reply": clean})


def ai_ask(params=None, **kw):
    import sys
    if sys.platform != "darwin":
        return _err("ai.ask 仅支持 macOS")

    script = 'display dialog "向 AI 提问：" default answer "" buttons {"取消","发送"} default button "发送"'
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        return _err("用户取消或 AppleScript 执行失败", returncode=r.returncode, stdout=r.stdout, stderr=r.stderr)

    m = re.search(r"text returned:(.*)", r.stdout)
    q = m.group(1).strip() if m else ""
    if not q:
        return _err("未输入任何问题")

    return ai_chat({"text": q, **(params or {})})


# ===================== 注册到调度器 =====================

def ensure_ai_chat_actions_registered(force: bool = False) -> None:
    """
    统一、可审计的 ai.* 注册入口。
    不再依赖 GUI 启动时的导入副作用，由调用方在真正使用 ai.chat 前显式确保。
    """
    global _ACTIONS_REGISTERED

    with _LOCK:
        if _ACTIONS_REGISTERED and not force:
            return

        if not force:
            meta = dispatcher.get_action("ai.chat")
            if meta is not None and getattr(meta, "module", None) == "model_engine_llamacpp":
                _ACTIONS_REGISTERED = True
                return

        dispatcher.register_action(
            "ai.use_llamacpp",
            ai_use_llamacpp,
            description="绑定 llama.cpp HTTP 端点（server-first）",
            module="model_engine_llamacpp",
        )
        dispatcher.register_action(
            "ai.set_model",
            ai_set_model,
            description="软选择模型（server-first：不切换权重）",
            module="model_engine_llamacpp",
        )
        dispatcher.register_action(
            "ai.chat",
            ai_chat,
            description="与本地 llama.cpp 聊天（server-first，protocol-safe）",
            module="model_engine_llamacpp",
        )
        dispatcher.register_action(
            "ai.ask",
            ai_ask,
            description="弹窗输入后聊天（macOS）",
            module="model_engine_llamacpp",
        )
        _ACTIONS_REGISTERED = True
        logger.info("✅ ensure_ai_chat_actions_registered: ai.* registered (server-first/hardened)")


def register_actions_llamacpp() -> None:
    """
    历史兼容入口。
    新代码应优先调用 ensure_ai_chat_actions_registered()。
    """
    ensure_ai_chat_actions_registered()
