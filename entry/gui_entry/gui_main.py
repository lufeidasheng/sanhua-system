#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三花聚顶 · GUI旗舰完整融合版（无思考过程优化 + 意图路由 + 动作误触发防护）🌸

关键策略：
- 默认：聊天只走 ai.chat / aicore.chat，不自动执行任何动作（防"你好→shutdown"事故）
- 支持显式命令：/ 或 ! 前缀，强制按动作执行
- 支持"自动动作：开/关"（默认关）：开后走 alias→intent→chat 三段式路由
- 按系统加载 aliases：config/aliases.yaml + config/aliases.{darwin|linux|win32}.yaml（存在则覆盖）
- 可选接入 IntentRecognizer / ActionSynthesizer：导入不到就降级，不影响 GUI
- SANHUA_REAL_ENV=1 强制真实环境
- SANHUA_DISABLE_DEMO=1 禁止演示降级（真实环境导入失败直接抛 Traceback）
"""

from __future__ import annotations
import sys, os, json, socket, threading, traceback, re, platform, time
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple, Callable

from PyQt6 import QtWidgets, QtGui, QtCore
from PyQt6.QtCore import Qt, QTimer

# ===== 强制真实环境开关（环境变量）=====
FORCE_REAL_ENV = os.environ.get("SANHUA_REAL_ENV", "0") in ("1", "true", "True")
DISABLE_DEMO_FALLBACK = os.environ.get("SANHUA_DISABLE_DEMO", "0") in ("1", "true", "True")

_REAL_IMPORT_ERR = None
_REAL_IMPORT_TB = None

# ---------------- HiDPI 兼容开关（Qt5/Qt6 通吃） ----------------
def enable_hidpi_safely():
    try:
        QtWidgets.QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    except Exception:
        pass
    try:
        QtWidgets.QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    except Exception:
        pass
    try:
        if hasattr(QtCore.Qt, "HighDpiScaleFactorRoundingPolicy"):
            from PyQt6.QtGui import QGuiApplication
            QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
                QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
            )
    except Exception:
        pass

# ========== 协议清洗函数（新增）==========
def _strip_llm_protocol(text: Any) -> Any:
    """
    彻底清除所有协议标记和思考过程
    支持处理：
    - ChatML标记：<|channel|>analysis<|message|>...</|end|>
    - 思考标记：<think>...</think>
    - 角色标记：assistant:, system:, 等
    """
    if not isinstance(text, str):
        return text
    
    t = text.strip()
    if not t:
        return t
    
    # 第1阶段：移除完整的分析通道
    # 匹配 <|channel|>analysis 到 <|end|> 之间的所有内容
    t = re.sub(r'<\|\s*channel\s*\|\s*>\s*analysis\s*<\|\s*message\s*\|\s*>.*?<\|\s*end\s*\|\s*>', 
               '', t, flags=re.IGNORECASE | re.DOTALL)
    
    # 第2阶段：移除 <|start|>assistant<|channel|>final<|message|> 标记
    t = re.sub(r'<\|\s*start\s*\|\s*>\s*\w*\s*<\|\s*channel\s*\|\s*>\s*final\s*<\|\s*message\s*\|\s*>', 
               '', t, flags=re.IGNORECASE)
    
    # 第3阶段：移除所有剩余的ChatML协议标记
    chatml_patterns = [
        r'<\|\s*channel\s*\|>',
        r'<\|\s*message\s*\|>',
        r'<\|\s*start\s*\|>',
        r'<\|\s*end\s*\|>',
        r'<\|\s*im_start\s*\|>',
        r'<\|\s*im_end\s*\|>',
    ]
    
    for pattern in chatml_patterns:
        t = re.sub(pattern, '', t, flags=re.IGNORECASE)
    
    # 第4阶段：移除所有类型的思考标记
    think_patterns = [
        r'<\s*think\s*>.*?<\s*/\s*think\s*>',
        r'<\s*thinking\s*>.*?<\s*/\s*thinking\s*>',
        r'<\s*reasoning\s*>.*?<\s*/\s*reasoning\s*>',
        r'<\s*analysis\s*>.*?<\s*/\s*analysis\s*>',
        r'<\s*step\s*>.*?<\s*/\s*step\s*>',
        r'<!--.*?-->',
        r'\[思考\].*?\[/思考\]',
        r'\[thinking\].*?\[/thinking\]',
    ]
    
    for pattern in think_patterns:
        t = re.sub(pattern, '', t, flags=re.IGNORECASE | re.DOTALL)
    
    # 第5阶段：移除角色标识
    role_patterns = [
        r'^\s*(assistant|ai|bot|system|user|model|llm)[:\s\-]*\s*',
        r'\s*(assistant|ai|bot|system|user|model|llm)[:\s\-]*\s*$',
    ]
    
    for pattern in role_patterns:
        t = re.sub(pattern, '', t, flags=re.IGNORECASE)
    
    # 第6阶段：清理空白字符
    t = re.sub(r'\s+', ' ', t)
    t = t.strip()
    
    # 第7阶段：如果结果为空，尝试提取纯文本内容
    if not t:
        lines = text.split('\n')
        clean_lines = []
        for line in lines:
            line_clean = line.strip()
            # 跳过明显是协议的行
            if not any(marker in line_clean.lower() for marker in ['<|', '|>', '<think', '</think', 'analysis:']):
                # 移除行内的协议标记
                line_clean = re.sub(r'<\|.*?\|>', '', line_clean)
                line_clean = re.sub(r'<[^>]*>', '', line_clean)
                if line_clean.strip():
                    clean_lines.append(line_clean.strip())
        
        t = ' '.join(clean_lines).strip()
        
        # 如果还是空的，返回原始文本的前100个字符
        if not t:
            t = text[:100].strip()
            if len(t) < len(text):
                t += "..."
    
    return t

# ========== 实环境优先，失败降级到演示环境（但可用环境变量禁止降级） ==========
REAL_ENV = True
try:
    from core.core2_0.sanhuatongyu.context_factory import create_system_context
    from core.core2_0.sanhuatongyu.module.manager import ModuleManager
    # ★ 统一单例：ACTION_MANAGER（避免多实例分裂）
    from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER as real_dispatcher
    from utils.alias_loader import load_aliases_from_yaml
except Exception as e:
    REAL_ENV = False
    real_dispatcher = None

    _REAL_IMPORT_ERR = e
    _REAL_IMPORT_TB = traceback.format_exc()

    if FORCE_REAL_ENV or DISABLE_DEMO_FALLBACK:
        raise RuntimeError(
            "真实环境初始化失败（已禁止演示降级）。\n"
            f"原始异常: {repr(e)}\n"
            f"Traceback:\n{_REAL_IMPORT_TB}"
        )

    def load_aliases_from_yaml(*a, **k) -> int:
        return 0

    def create_system_context(entry_mode="gui"):
        class _DummyDispatcher:
            def list_actions(self, detailed=False):
                return [
                    {"name": "aicore.chat", "description": "AI 对话（兜底）"},
                    {"name": "system.health_check", "description": "系统健康检查"},
                    {"name": "get_system_metrics", "description": "系统指标 JSON"},
                    {"name": "tts.speak", "description": "TTS 播报"},
                ]

            def execute(self, name, *args, **kwargs):
                params = (kwargs or {}).get("params") or {}
                if name == "aicore.chat":
                    q = params.get("query", "")
                    return {"response": f"（演示环境）你说：{q}"}
                if name == "system.health_check":
                    return {
                        "status": "READY",
                        "health": "OK",
                        "modules": {
                            "aicore": {"status": "READY", "version": "1.0"},
                            "model_engine": {"status": "READY", "version": "3.1"},
                            "tts": {"status": "READY", "version": "1.0"},
                        },
                    }
                if name == "get_system_metrics":
                    return {"metrics": {"cpu": {"percent": 12.3}}}
                if name == "tts.speak":
                    return "speaking..."
                return {"ok": True, "name": name, "params": params}

            # 为了兼容某些 UI/路由逻辑
            def match_action(self, text: str):
                return None

        class _MM:
            def __init__(self, *a, **k): pass
            def load_modules_metadata(self): pass
            def load_modules(self, mode): pass
            def start_modules(self): pass
            def stop_modules(self): pass
            def restart_module(self, m): pass
            def unload_module(self, m): pass

        class _Ctx:
            def __init__(self):
                self.action_dispatcher = _DummyDispatcher()
                self.module_manager = _MM()
            def get_config(self, k, d=None):
                if k == "modules_dir":
                    return os.path.join(os.getcwd(), "modules")
                return d
            def call_action(self, name, params=None):
                return self.action_dispatcher.execute(name, params=params or {})

        return _Ctx()

    class ModuleManager:  # type: ignore
        def __init__(self, *a, **k): pass
        def load_modules_metadata(self): pass
        def load_modules(self, *a, **k): pass
        def start_modules(self): pass
        def stop_modules(self): pass
        def restart_module(self, m): pass
        def unload_module(self, m): pass

# AICore 直连（可选兜底）
try:
    from core.aicore.aicore import get_aicore_instance
except Exception:
    get_aicore_instance = None  # 兜底演示

# 记忆中心 Dock（可选）
try:
    from core.gui.memory_dock import MemoryDock
except Exception:
    MemoryDock = None

# --- llama.cpp 兼容补丁（ai.* 注册由统一入口按需确保） ---
_LLM_ACTIONS_READY = False
try:
    os.environ.setdefault("SANHUA_LLAMA_BASE_URL", "http://127.0.0.1:8080/v1")
    from core.core2_0.sanhuatongyu.services.model_engine.engine_compat import install as _me_install
    _me_install()
    _LLM_ACTIONS_READY = True
except Exception:
    _LLM_ACTIONS_READY = False

# ===== 可选：IntentRecognizer / ActionSynthesizer 接入（导入失败不影响 GUI）=====
IntentRecognizer = None
ActionSynthesizer = None
_INTENT_ERR = None
try:
    # 你项目里真实路径可能不同：这里尽量"多路径兜底"
    try:
        from core.core2_0.sanhuatongyu.intent.intent_recognizer import IntentRecognizer  # type: ignore
    except Exception:
        from core.core2_0.sanhuatongyu.intent_recognizer import IntentRecognizer  # type: ignore

    try:
        from core.core2_0.sanhuatongyu.action_synthesizer import ActionSynthesizer  # type: ignore
    except Exception:
        from core.core2_0.sanhuatongyu.action_synthesizer_v2 import ActionSynthesizer  # type: ignore
except Exception as e:
    _INTENT_ERR = traceback.format_exc()
    IntentRecognizer = None
    ActionSynthesizer = None

# ========== 资源路径 ==========
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "../../assets")
os.makedirs(ASSETS_DIR, exist_ok=True)
BG_IMAGE = os.path.join(ASSETS_DIR, "bg_landscape.jpg")
AVATAR_DIR = os.path.join(ASSETS_DIR, "avatars")
os.makedirs(AVATAR_DIR, exist_ok=True)
AVATAR_GIF = os.path.join(AVATAR_DIR, "default.gif")
AVATAR_PNG = os.path.join(AVATAR_DIR, "default.png")

# ========== 主题 ==========
class Theme:
    BG = "#0b0c0e"
    SUR = "#121418"
    CARD = "#15171a"
    TEXT = "#e9ecf1"
    SUB = "#9aa3ad"
    BORDER = "#22252b"
    ACCENT = "#66a8ff"

    @staticmethod
    def apply(app: QtWidgets.QApplication):
        pal = app.palette()
        pal.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(Theme.BG))
        pal.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(Theme.CARD))
        pal.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor(Theme.TEXT))
        pal.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor(Theme.TEXT))
        pal.setColor(QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor(Theme.TEXT))
        pal.setColor(QtGui.QPalette.ColorRole.Highlight, QtGui.QColor(Theme.ACCENT))
        pal.setColor(QtGui.QPalette.ColorRole.HighlightedText, QtGui.QColor("#ffffff"))
        app.setPalette(pal)
        app.setStyle("Fusion")
        app.setStyleSheet(
            f"""
        QMainWindow {{ background:{Theme.BG}; }}
        QLabel, QTableWidget, QTextEdit, QLineEdit, QListWidget, QPlainTextEdit {{
            color:{Theme.TEXT}; font-size:15px;
        }}
        QFrame, QTextEdit, QLineEdit, QListWidget, QTableWidget, QPlainTextEdit {{
            background:{Theme.CARD}; border:1px solid {Theme.BORDER}; border-radius:10px;
        }}
        QPushButton {{
            background:#1b1e23; border:1px solid {Theme.BORDER}; border-radius:10px; padding:6px 12px; color:{Theme.TEXT};
        }}
        QPushButton:hover {{ border-color:{Theme.ACCENT}; }}
        QPushButton:pressed {{ background:#111316; }}
        QTableWidget::item:selected {{ background:{Theme.ACCENT}; color:white; }}
        #status_capsule {{ border:1px solid {Theme.BORDER}; border-radius:12px; background:#121418; }}
        """
        )

def make_pill_button(text: str, minw: int = 96, minh: int = 34) -> QtWidgets.QPushButton:
    btn = QtWidgets.QPushButton(text)
    fm = btn.fontMetrics()
    need_w = fm.horizontalAdvance(text) + 28
    btn.setMinimumWidth(max(minw, need_w))
    btn.setMinimumHeight(minh)
    btn.setSizePolicy(
        QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Fixed
    )
    btn.setStyleSheet(
        """
        QPushButton{
            background:#1b1e23; color:#e9ecf1;
            border:1px solid #2a2d33; border-radius:999px;
            padding:6px 12px;
        }
        QPushButton:hover{ border-color:#66a8ff; }
        QPushButton:pressed{ background:#14171b; }
        QPushButton:disabled{ color:#889; border-color:#223; }
    """
    )
    return btn

# ========== 工具 ==========
def http_get_json(url: str, timeout=2.0) -> Optional[dict]:
    import http.client, json as _j, urllib.parse
    try:
        u = urllib.parse.urlparse(url)
        conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout)
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
        conn.request("GET", path)
        resp = conn.getresponse()
        if 200 <= resp.status < 300:
            data = resp.read()
            conn.close()
            return _j.loads(data.decode("utf-8") or "{}")
        conn.close()
    except Exception:
        pass
    return None

def tcp_alive(host="127.0.0.1", port=11434, timeout=0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

# ---- 状态/健康 映射 ----
STATUS_MAP = {
    "OK": ("正常", "#0f9150"),
    "READY": ("就绪", "#0f9150"),
    "WARNING": ("警告", "#b58900"),
    "DEGRADED": ("降级", "#d97706"),
    "ERROR": ("错误", "#d14343"),
    "CRITICAL": ("严重", "#b91c1c"),
    "UNKNOWN": ("未知", "#6b7280"),
    "FAILED": ("失败", "#d14343"),
}
HEALTH_MAP = STATUS_MAP

def _normalize_key(s: str) -> str:
    return (s or "").strip().upper() if isinstance(s, str) else "UNKNOWN"

def translate_status(raw: str) -> Tuple[str, str]:
    return STATUS_MAP.get(_normalize_key(raw), ("未知", "#6b7280"))

def translate_health(raw: str) -> Tuple[str, str]:
    return HEALTH_MAP.get(_normalize_key(raw), ("未知", "#6b7280"))

def detect_platform_key() -> str:
    # darwin / linux / win32
    return sys.platform.lower()

def platform_display() -> str:
    return f"{platform.system()} {platform.release()} ({sys.platform})"

def pretty_exc(e: BaseException) -> str:
    return f"{repr(e)}\n{traceback.format_exc()}"

# ========== 路由：alias → intent → chat（带误触发防护） ==========
@dataclass
class RoutedResult:
    kind: str               # "action" | "chat"
    reply: str              # 展示给用户的文本
    action_name: str = ""
    action_params: Optional[dict] = None
    action_result: Any = None
    chain_steps: Optional[List[str]] = None

class ActionRouter:
    """
    路由原则：
    - 默认：不自动执行动作（auto_action=False）
    - 显式命令：/ 或 ! 前缀强制走动作
    - auto_action=True 时：alias → intent → chat
    """
    def __init__(
        self,
        call_action: Callable[[str, dict], Any],
        list_actions: Callable[[], List[dict]],
        dispatcher_obj: Any,
        log: Callable[[str], None],
    ):
        self.call_action = call_action
        self.list_actions = list_actions
        self.dispatcher_obj = dispatcher_obj
        self.log = log

        self.auto_action_enabled = False  # 默认关
        self.intent_enabled = True         # 允许识别（但受 auto_action 控制）
        self.safe_mode = True             # 防误触发：危险动作必须显式命令

        # 一组"默认危险动作"，你后续可以做成配置
        self.danger_actions = {
            "shutdown", "poweroff", "reboot",
            "system.shutdown", "system.poweroff", "system.reboot",
            "lock_screen", "sys.lock", "sys.power.off"
        }

        # 尝试初始化 Intent 组件（存在则启用）
        self._ir = None
        self._syn = None
        try:
            if IntentRecognizer and ActionSynthesizer:
                self._ir = IntentRecognizer()
                self._syn = ActionSynthesizer()
        except Exception:
            self._ir = None
            self._syn = None

    def set_auto_action(self, enabled: bool):
        self.auto_action_enabled = bool(enabled)

    def _is_explicit_command(self, text: str) -> bool:
        t = (text or "").strip()
        return t.startswith("/") or t.startswith("!")

    def _strip_command_prefix(self, text: str) -> str:
        t = (text or "").strip()
        if t.startswith("/") or t.startswith("!"):
            return t[1:].strip()
        return t

    def _normalize_user_text(self, text: str) -> str:
        t = (text or "").strip()
        # 统一全角标点/空白
        t = re.sub(r"\s+", " ", t)
        return t

    def _action_exists(self, name: str) -> bool:
        try:
            acts = self.list_actions() or []
            return any((a.get("name") == name) for a in acts if isinstance(a, dict))
        except Exception:
            return False

    def _match_alias(self, text: str) -> Optional[Tuple[str, dict]]:
        """
        兼容你 Dispatcher 可能存在的 match_action / resolve_alias / match 等方法。
        返回 (action_name, params)
        """
        disp = self.dispatcher_obj
        if not disp:
            return None

        t = text.strip()
        if not t:
            return None

        # 1) match_action(text) -> str | dict | tuple
        for fn_name in ("match_action", "resolve_alias", "match"):
            if hasattr(disp, fn_name):
                try:
                    hit = getattr(disp, fn_name)(t)
                    if not hit:
                        continue
                    # 允许多种返回形态
                    if isinstance(hit, str):
                        return hit, {}
                    if isinstance(hit, tuple) and len(hit) == 2:
                        return hit[0], (hit[1] or {})
                    if isinstance(hit, dict):
                        name = hit.get("name") or hit.get("action") or hit.get("action_name")
                        params = hit.get("params") or {}
                        if name:
                            return str(name), dict(params)
                except Exception:
                    continue

        # 2) 如果没有匹配接口，就放弃
        return None

    def _intent_recognize(self, text: str) -> Optional[Tuple[str, dict]]:
        """
        尝试用 IntentRecognizer + Synthesizer，把自然语言变成 (action_name, params)
        如果你 Synthesizer 的实现是"返回可调用函数"，这里也做兼容。
        """
        if not (self._ir and self._syn):
            return None

        try:
            intent = self._ir.recognize(text) if hasattr(self._ir, "recognize") else None
            if not intent:
                return None

            # Synthesizer 兼容：可能返回 (name, params) 或 callable 或 dict
            out = self._syn.synthesize(intent) if hasattr(self._syn, "synthesize") else None
            if not out:
                return None

            if callable(out):
                # 如果是可调用，无法静态取 name：这里保守返回 None，让 chat 接管
                return None

            if isinstance(out, tuple) and len(out) == 2:
                name, params = out
                if name:
                    return str(name), (params or {})
            if isinstance(out, dict):
                name = out.get("name") or out.get("action") or out.get("action_name")
                params = out.get("params") or {}
                if name:
                    return str(name), dict(params)
        except Exception:
            return None

        return None

    def route(self, text: str) -> Optional[RoutedResult]:
        """
        返回 RoutedResult：
        - kind="action"：说明执行了动作（或准备执行）
        - kind="chat"：说明应走聊天（ai.chat / aicore.chat）
        """
        raw = text or ""
        text = self._normalize_user_text(raw)

        if not text:
            return RoutedResult(kind="chat", reply="", chain_steps=["User", "Empty"])

        explicit = self._is_explicit_command(text)
        payload = self._strip_command_prefix(text) if explicit else text

        # 1) 显式命令：强制 alias → intent → 失败提示
        if explicit:
            chain = ["User", "CommandPrefix", "Alias/Intent", "Action", "Done"]
            hit = self._match_alias(payload) or self._intent_recognize(payload)
            if not hit:
                return RoutedResult(
                    kind="action",
                    reply=f"未识别到可执行动作：{payload}",
                    chain_steps=chain,
                )

            name, params = hit
            if self.safe_mode and name in self.danger_actions:
                # 显式命令本来就允许危险动作，这里只做提示
                pass

            return RoutedResult(
                kind="action",
                reply=f"准备执行动作：{name}",
                action_name=name,
                action_params=params,
                chain_steps=chain,
            )

        # 2) 非显式：默认不执行动作（除非 auto_action_enabled）
        if not self.auto_action_enabled:
            return RoutedResult(kind="chat", reply="", chain_steps=["User", "ChatOnly"])

        # 3) auto_action=True：alias → intent → chat
        chain = ["User", "AutoAction", "Alias", "Intent", "Route", "Done"]

        hit = self._match_alias(payload)
        if hit:
            name, params = hit
            if self.safe_mode and name in self.danger_actions:
                # 防止"你好→shutdown"这类事故：危险动作必须显式命令
                return RoutedResult(
                    kind="chat",
                    reply="",
                    chain_steps=["User", "AutoAction", "AliasHit(DangerBlocked)", "ChatFallback"],
                )
            return RoutedResult(
                kind="action",
                reply=f"识别到动作：{name}",
                action_name=name,
                action_params=params,
                chain_steps=["User", "AutoAction", "AliasHit", "Action", "Done"],
            )

        hit2 = self._intent_recognize(payload) if self.intent_enabled else None
        if hit2:
            name, params = hit2
            if self.safe_mode and name in self.danger_actions:
                return RoutedResult(
                    kind="chat",
                    reply="",
                    chain_steps=["User", "AutoAction", "IntentHit(DangerBlocked)", "ChatFallback"],
                )
            return RoutedResult(
                kind="action",
                reply=f"识别到意图动作：{name}",
                action_name=name,
                action_params=params,
                chain_steps=["User", "AutoAction", "IntentHit", "Action", "Done"],
            )

        return RoutedResult(kind="chat", reply="", chain_steps=["User", "AutoAction", "NoHit", "ChatFallback"])


def _action_name_in_list(actions, name: str) -> bool:
    if not name:
        return False
    if isinstance(actions, dict):
        return name in actions
    if not isinstance(actions, list):
        return False
    for item in actions:
        if item == name:
            return True
        if isinstance(item, dict) and item.get("name") == name:
            return True
    return False


def _context_has_action(ctx, name: str) -> bool:
    disp = getattr(ctx, "action_dispatcher", None)
    if disp is None or not hasattr(disp, "list_actions"):
        return False
    try:
        if _action_name_in_list(disp.list_actions(detailed=True), name):
            return True
    except Exception:
        pass
    try:
        return _action_name_in_list(disp.list_actions(), name)
    except Exception:
        return False


# ========== 模型运行时 ==========
class ModelRuntime(QtCore.QObject):
    status_changed = QtCore.pyqtSignal(dict)

    def __init__(self, context, ac=None):
        super().__init__()
        self.ctx = context
        self.ac = ac
        self.current_backend = "auto"
        self.current_model = ""
        self.backends: Dict[str, dict] = {}
        self.models: Dict[str, List[dict]] = {"ollama": [], "llamacpp": [], "openai": []}
        self._lock = threading.RLock()
        self.refresh_async()

    def get_status(self) -> dict:
        with self._lock:
            return {
                "backend": self.current_backend,
                "model": self.current_model,
                "backends": self.backends,
                "models": self.models,
            }

    def set_backend(self, name: str):
        with self._lock:
            self.current_backend = name or "auto"
        self.status_changed.emit(self.get_status())

    def set_model(self, model_name: str):
        ok = False
        if _context_has_action(self.ctx, "ai.set_model"):
            try:
                self.ctx.call_action("ai.set_model", params={"name": model_name})
                ok = True
            except Exception:
                ok = False

        if not ok and self.ac and hasattr(self.ac, "model_engine"):
            try:
                self.ac.model_engine.select_model(model_name)
                ok = True
            except Exception:
                ok = False

        if not ok:
            try:
                self.ctx.call_action("model_engine.select_model", {"name": model_name})
                ok = True
            except Exception:
                ok = False

        with self._lock:
            self.current_model = model_name
        self.status_changed.emit(self.get_status())
        return ok

    def refresh_async(self):
        def safe_refresh():
            try:
                self._do_refresh()
            except Exception as e:
                print(f"模型刷新失败: {e}")
        threading.Thread(target=safe_refresh, name="ModelRefresh", daemon=True).start()

    def _do_refresh(self):
        info = {
            "ollama": {"alive": False, "url": "http://127.0.0.1:11434"},
            "llamacpp": {"alive": False, "url": "http://127.0.0.1:8080"},
            "openai": {"alive": False, "note": "如已配置由后端动作接管"},
        }
        if tcp_alive("127.0.0.1", 11434):
            info["ollama"]["alive"] = True
            tags = http_get_json("http://127.0.0.1:11434/api/tags") or {}
            arr = []
            for m in (tags.get("models") or []):
                arr.append(
                    {"name": m.get("name"), "size": m.get("size"),
                     "family": (m.get("details") or {}).get("family")}
                )
            self.models["ollama"] = arr
            if not self.current_model and arr:
                self.current_model = arr[0]["name"]

        if tcp_alive("127.0.0.1", 8080):
            info["llamacpp"]["alive"] = True
            m1 = http_get_json("http://127.0.0.1:8080/v1/models") or {}
            names = []
            raw_list = (m1.get("data") or []) or (m1.get("models") or [])
            for it in raw_list:
                mid = it.get("id") or it.get("root") or it.get("model") or it.get("name") or ""
                name = os.path.basename(mid) if mid else mid
                if name:
                    names.append({"name": name})
            self.models["llamacpp"] = names
            if not self.current_model and names:
                self.current_model = names[0]["name"]

        with self._lock:
            self.backends = info
        self.status_changed.emit(self.get_status())

# ========== 子组件 ==========
class SystemMonitorDock(QtWidgets.QDockWidget):
    def __init__(self, ctx, parent=None):
        super().__init__("系统监控", parent)
        self.ctx = ctx
        self.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable |
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self.banner = QtWidgets.QLabel("系统监控：初始化中…")
        self.banner.setStyleSheet("font-weight:bold;color:#cfd6de;")
        lay.addWidget(self.banner)

        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["指标", "数值"])
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QtWidgets.QTableWidget.EditTrigger.NoEditTriggers)
        lay.addWidget(self.table, 1)

        foot = QtWidgets.QHBoxLayout()
        btn = make_pill_button("立即刷新", minw=96, minh=30)
        btn.clicked.connect(self.refresh_now)
        foot.addWidget(btn)
        self.auto_label = QtWidgets.QLabel("每 10 秒自动刷新")
        self.auto_label.setStyleSheet(f"color:{Theme.SUB};")
        foot.addStretch()
        foot.addWidget(self.auto_label)
        lay.addLayout(foot)

        self.setWidget(w)
        self.timer = QTimer(self)
        self.timer.setInterval(10_000)
        self.timer.timeout.connect(self.safe_refresh)
        self.timer.start()
        QtCore.QTimer.singleShot(120, self.safe_refresh)

    def safe_refresh(self):
        try:
            self.refresh_now()
        except Exception as e:
            self.banner.setText(f"系统监控：刷新失败 {e}")

    def refresh_now(self):
        status = metrics = None
        try:
            status = self.ctx.call_action("get_system_status")
        except Exception:
            pass
        try:
            metrics = self.ctx.call_action("get_system_metrics")
        except Exception:
            pass

        if not (status or metrics):
            self.banner.setText("系统监控：未检测到 system_monitor 模块（或动作未注册）")
            self.table.setRowCount(0)
            return

        self.banner.setText(status.splitlines()[0][:160] if isinstance(status, str) else "系统监控：运行中")
        self.table.setRowCount(0)
        m = (metrics or {}).get("metrics", {}) if isinstance(metrics, dict) else {}

        def add(k, v):
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(k))
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(v))

        cpu = m.get("cpu", {})
        mem = m.get("memory", {})
        disk = m.get("disk", {})
        net = m.get("network", {})
        temp = m.get("temperature", {})

        add("CPU 使用率", f"{cpu.get('percent', 0):.1f}%")
        add("内存 使用率", f"{mem.get('percent', 0):.1f}%")
        add("磁盘 使用率", f"{disk.get('usage_percent', 0):.1f}%")
        add("网络 上+下(MB)", f"{(net.get('bytes_sent', 0)+net.get('bytes_recv', 0))/(1024**2):.1f}")
        if temp:
            sensor, t = max(temp.items(), key=lambda kv: kv[1])
            add("最高温度", f"{sensor}: {t:.1f}°C")

class AvatarDock(QtWidgets.QDockWidget):
    def __init__(self, parent=None):
        super().__init__("虚拟形象", parent)
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable |
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        wrap = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(wrap)
        lay.setContentsMargins(6, 6, 6, 6)

        self.label = QtWidgets.QLabel("加载中…")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setMinimumSize(220, 260)
        self.label.setStyleSheet("background:#0f1114;border:1px solid #222; border-radius:10px;")
        lay.addWidget(self.label)
        self.setWidget(wrap)

        self.movie = None
        self._load_avatar_media()

    def _load_avatar_media(self):
        if os.path.exists(AVATAR_GIF):
            self.movie = QtGui.QMovie(AVATAR_GIF)
            self.movie.setCacheMode(QtGui.QMovie.CacheMode.CacheAll)
            self.movie.setSpeed(100)
            self.label.setMovie(self.movie)
            self.movie.start()
        elif os.path.exists(AVATAR_PNG):
            self._set_pixmap(AVATAR_PNG)
        else:
            self.label.setText("请放置 assets/avatars/default.gif 或 default.png")

    def _set_pixmap(self, path):
        pix = QtGui.QPixmap(path)
        if not pix.isNull():
            self.label.setPixmap(pix.scaled(
                self.label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def resizeEvent(self, e: QtGui.QResizeEvent) -> None:
        super().resizeEvent(e)
        if self.movie is None and os.path.exists(AVATAR_PNG):
            self._set_pixmap(AVATAR_PNG)

class ChatBubble(QtWidgets.QWidget):
    def __init__(self, text, is_user=False):
        super().__init__()
        layout = QtWidgets.QHBoxLayout(self)
        label = QtWidgets.QLabel(text)
        label.setWordWrap(True)
        label.setMinimumHeight(36)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        if is_user:
            label.setStyleSheet("background:#1a2218;border-radius:10px;padding:6px 12px;color:#e6f6e6;")
            layout.addStretch()
            layout.addWidget(label)
        else:
            label.setStyleSheet("background:#16202e;border-radius:10px;padding:6px 12px;color:#e6eef7;")
            layout.addWidget(label)

            btn_copy = make_pill_button("复制", minw=58, minh=26)
            btn_copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(text))
            layout.addWidget(btn_copy)
            layout.addStretch()

class ChatPanel(QtWidgets.QWidget):
    def __init__(self, send_callback, tts_control_callback=None):
        super().__init__()
        self.send_callback = send_callback
        self.tts_enabled = True
        self.last_ai_reply = ""

        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)

        self.bg = QtWidgets.QLabel()
        if os.path.exists(BG_IMAGE):
            pixmap = QtGui.QPixmap(BG_IMAGE)
            if not pixmap.isNull():
                self.bg.setPixmap(pixmap.scaled(440, 260, Qt.AspectRatioMode.KeepAspectRatioByExpanding))
        if self.bg.pixmap() is None or self.bg.pixmap().isNull():
            px = QtGui.QPixmap(1, 1)
            px.fill(QtGui.QColor(0, 0, 0, 0))
            self.bg.setPixmap(px)
        self.bg.setStyleSheet("border-radius:14px;margin:6px;")
        v.addWidget(self.bg)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.chat_widget = QtWidgets.QWidget()
        self.chat_layout = QtWidgets.QVBoxLayout(self.chat_widget)
        self.chat_layout.addStretch()
        self.scroll.setWidget(self.chat_widget)
        v.addWidget(self.scroll, 1)

        h = QtWidgets.QHBoxLayout()
        self.input = QtWidgets.QLineEdit()
        self.input.setPlaceholderText("聊天默认不执行动作；用 /xxx 或开启'自动动作'触发指令（Ctrl+K 命令面板）")
        self.input.returnPressed.connect(self.on_send)
        h.addWidget(self.input)

        btn = make_pill_button("发送", minw=72)
        btn.clicked.connect(self.on_send)
        h.addWidget(btn)
        v.addLayout(h)

        tools = QtWidgets.QHBoxLayout()
        self.tts_btn = make_pill_button("🔊语音播报: 开", minw=130)
        self.tts_btn.setCheckable(True)
        self.tts_btn.setChecked(True)
        self.tts_btn.clicked.connect(self.toggle_tts)
        tools.addWidget(self.tts_btn)

        clear = make_pill_button("清空会话", minw=96)
        clear.clicked.connect(self.clear_chat)
        tools.addWidget(clear)

        tools.addStretch()
        v.addLayout(tools)

        self.tts_control_callback = tts_control_callback

    def toggle_tts(self):
        self.tts_enabled = not self.tts_enabled
        self.tts_btn.setText(f"🔊语音播报: {'开' if self.tts_enabled else '关'}")
        if self.tts_control_callback:
            self.tts_control_callback(self.tts_enabled)

    def clear_chat(self):
        for i in reversed(range(self.chat_layout.count() - 1)):
            w = self.chat_layout.itemAt(i).widget()
            if w:
                w.deleteLater()
        self.last_ai_reply = ""

    def on_send(self):
        t = self.input.text().strip()
        if not t:
            return
        self.add_bubble(t, is_user=True)
        self.input.clear()
        QtCore.QTimer.singleShot(60, lambda: self.send_callback(t))

    def add_bubble(self, text, is_user=False):
        b = ChatBubble(text, is_user)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, b)
        if not is_user:
            self.last_ai_reply = text
        QtCore.QTimer.singleShot(40, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))

class ModuleTable(QtWidgets.QTableWidget):
    def __init__(self, owner_getter):
        super().__init__()
        self._owner_getter = owner_getter
        self.setColumnCount(5)
        self.setHorizontalHeaderLabels(["模块", "状态", "健康", "版本", "操作"])
        self.setEditTriggers(QtWidgets.QTableWidget.EditTrigger.NoEditTriggers)
        self.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.setShowGrid(True)

    def update_modules(self, modules: dict):
        self.setRowCount(0)
        for idx, (mod, data) in enumerate(modules.items()):
            self.insertRow(idx)
            self.setItem(idx, 0, QtWidgets.QTableWidgetItem(mod))

            raw_status = data.get("status", "UNKNOWN")
            zh, color = translate_status(raw_status)
            s_item = QtWidgets.QTableWidgetItem(zh)
            s_item.setToolTip(f"原始: {raw_status}")
            s_item.setForeground(QtGui.QBrush(QtGui.QColor(color)))
            self.setItem(idx, 1, s_item)

            raw_health = data.get("health", data.get("status", "UNKNOWN"))
            zh2, color2 = translate_health(raw_health)
            h_item = QtWidgets.QTableWidgetItem(zh2)
            h_item.setToolTip(f"原始: {raw_health}")
            h_item.setForeground(QtGui.QBrush(QtGui.QColor(color2)))
            self.setItem(idx, 2, h_item)

            self.setItem(idx, 3, QtWidgets.QTableWidgetItem(data.get("version", "")))

            w = QtWidgets.QWidget()
            l = QtWidgets.QHBoxLayout(w)
            l.setContentsMargins(0, 0, 0, 0)

            b1 = make_pill_button("重启", minw=66, minh=26)
            b1.clicked.connect(lambda _, m=mod: self._owner_getter().restart_module(m))
            b2 = make_pill_button("卸载", minw=66, minh=26)
            b2.clicked.connect(lambda _, m=mod: self._owner_getter().unload_module(m))

            l.addWidget(b1)
            l.addWidget(b2)
            self.setCellWidget(idx, 4, w)

class CommandPalette(QtWidgets.QDialog):
    triggered = QtCore.pyqtSignal(dict)

    def __init__(self, list_actions_callable, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Command Palette")
        self.setModal(True)
        self.resize(620, 520)
        self._list_actions_callable = list_actions_callable
        self.input = QtWidgets.QLineEdit(self)
        self.input.setPlaceholderText("输入动作/关键词（Ctrl+K 随时打开）")
        self.list = QtWidgets.QListWidget(self)

        v = QtWidgets.QVBoxLayout(self)
        v.addWidget(self.input)
        v.addWidget(self.list)

        self.input.textChanged.connect(self._filter)
        self.list.itemActivated.connect(self._activate)
        self._refresh()

    def _refresh(self):
        self._actions = []
        try:
            acts = self._list_actions_callable() or []
            for a in acts:
                self._actions.append({
                    "name": a.get("name"),
                    "description": a.get("description", ""),
                    "module": a.get("module") or "",
                    "aliases": a.get("aliases", []),
                })
        except Exception:
            self._actions = []
        self._populate(self._actions)

    def _populate(self, data):
        self.list.clear()
        for a in data:
            aliases = ", ".join(a.get("aliases", []))
            text = f"{a['name']} — {a.get('description', '')}"
            if aliases:
                text += f"  ({aliases})"
            it = QtWidgets.QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, a)
            self.list.addItem(it)

    def _filter(self, s: str):
        s = (s or "").strip().lower()
        if not s:
            self._populate(self._actions)
            return
        filtered = [
            a for a in self._actions
            if s in f"{a['name']} {a.get('description','')} {' '.join(a.get('aliases', []))} {a.get('module','')}".lower()
        ]
        self._populate(filtered)

    def _activate(self, item):
        a = item.data(Qt.ItemDataRole.UserRole)
        self.triggered.emit(a)
        self.accept()

class ActionRunnerDialog(QtWidgets.QDialog):
    def __init__(self, action_name: str, caller, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"测试动作：{action_name}")
        self.resize(560, 460)
        self.action_name = action_name
        self._caller = caller

        self.ed = QtWidgets.QPlainTextEdit(self)
        self.ed.setPlaceholderText('在此输入 JSON 参数，例如：{"text":"你好"}')
        self.ed.setPlainText("{}")

        self.btn = make_pill_button("执行", minw=80)
        self.out = QtWidgets.QPlainTextEdit()
        self.out.setReadOnly(True)

        v = QtWidgets.QVBoxLayout(self)
        v.addWidget(QtWidgets.QLabel(f"动作：{action_name}"))
        v.addWidget(self.ed, 1)

        h = QtWidgets.QHBoxLayout()
        h.addStretch()
        h.addWidget(self.btn)
        v.addLayout(h)

        v.addWidget(QtWidgets.QLabel("输出："))
        v.addWidget(self.out, 1)

        self.btn.clicked.connect(self._run)

    def _run(self):
        raw = self.ed.toPlainText().strip()
        try:
            params = json.loads(raw) if raw else {}
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "参数错误", f"JSON 解析失败：{e}")
            return
        try:
            res = self._caller(self.action_name, params=params)
        except Exception as e:
            res = f"执行异常：{e}\n{traceback.format_exc()}"
        self.out.setPlainText(json.dumps(res, ensure_ascii=False, indent=2) if not isinstance(res, str) else res)

class ActionChainView(QtWidgets.QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHints(QtGui.QPainter.RenderHint.Antialiasing | QtGui.QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
        self.scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self.scene)
        self._nodes = []
        self._edges = []
        self._timer = None
        self._idx = 0

    def clear(self):
        self.scene.clear()
        self._nodes = []
        self._edges = []
        self._idx = 0
        if self._timer:
            self._timer.stop()

    def show_chain(self, steps: List[str], animate=True, interval_ms=160):
        self.clear()
        x, y = 0, 0
        prev = None
        edges = []
        nodes = []
        for s in steps:
            g = self._node(s, x, y)
            nodes.append(g)
            if prev:
                edges.append(self._edge(prev, g))
            prev = g
            x += 220

        self._nodes = nodes
        self._edges = edges
        if animate:
            self._idx = 0
            self._timer = QTimer(self)
            self._timer.setInterval(interval_ms)
            self._timer.timeout.connect(self._tick)
            self._timer.start()
        else:
            for g in self._nodes:
                self._highlight_node(g, True)
            for e in self._edges:
                self._highlight_edge(e, True)

    def _tick(self):
        if self._idx < len(self._nodes):
            self._highlight_node(self._nodes[self._idx], True)
            if self._idx > 0:
                self._highlight_edge(self._edges[self._idx - 1], True)
            self._idx += 1
        else:
            if self._timer:
                self._timer.stop()

    def _node(self, text, x, y):
        rect = QtCore.QRectF(0, 0, 200, 56)
        grp = QtWidgets.QGraphicsItemGroup()
        r = QtWidgets.QGraphicsRectItem(rect)
        r.setBrush(QtGui.QColor("#1a1c21"))
        r.setPen(QtGui.QPen(QtGui.QColor("#2a2d33"), 1.2))
        t = QtWidgets.QGraphicsTextItem(text)
        t.setDefaultTextColor(QtGui.QColor("#cfd6de"))
        t.setPos(10, 12)
        grp.addToGroup(r)
        grp.addToGroup(t)
        grp.setPos(x, y)
        self.scene.addItem(grp)
        return grp

    def _edge(self, a, b):
        ap = a.pos()
        bp = b.pos()
        y = ap.y() + 28
        line = self.scene.addLine(ap.x() + 200, y, bp.x(), y, QtGui.QPen(QtGui.QColor(Theme.ACCENT), 1.6))
        line.setZValue(-1)
        line.setOpacity(0.55)
        return line

    def _highlight_node(self, g, on):
        for c in g.childItems():
            if isinstance(c, QtWidgets.QGraphicsRectItem):
                c.setBrush(QtGui.QColor("#20242a" if on else "#1a1c21"))
                c.setPen(QtGui.QPen(QtGui.QColor(Theme.ACCENT if on else "#2a2d33"), 2 if on else 1.2))
            elif isinstance(c, QtWidgets.QGraphicsTextItem):
                c.setDefaultTextColor(QtGui.QColor("#eef3fb" if on else "#cfd6de"))

    def _highlight_edge(self, e, on):
        p = e.pen()
        p.setColor(QtGui.QColor(Theme.ACCENT))
        p.setWidthF(2.2 if on else 1.6)
        e.setPen(p)
        e.setOpacity(0.9 if on else 0.55)

class ModelCenter(QtWidgets.QWidget):
    def __init__(self, runtime: ModelRuntime):
        super().__init__()
        self.runtime = runtime
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)

        ht = QtWidgets.QHBoxLayout()
        self.title = QtWidgets.QLabel("模型中心 · 后端与模型")
        self.title.setStyleSheet("font-weight:600;")
        self.btn_refresh = make_pill_button("刷新")
        self.btn_refresh.clicked.connect(self.runtime.refresh_async)
        ht.addWidget(self.title)
        ht.addStretch()
        ht.addWidget(self.btn_refresh)
        v.addLayout(ht)

        self.lbl_backend = QtWidgets.QLabel("后端：检测中…")
        self.lbl_model = QtWidgets.QLabel("模型：—")
        self.lbl_backend.setStyleSheet(f"color:{Theme.SUB};")
        self.lbl_model.setStyleSheet(f"color:{Theme.SUB};")
        v.addWidget(self.lbl_backend)
        v.addWidget(self.lbl_model)

        self.group_backends = QtWidgets.QGroupBox("可用后端")
        gbv = QtWidgets.QVBoxLayout(self.group_backends)
        self.list_backends = QtWidgets.QListWidget()
        gbv.addWidget(self.list_backends)
        v.addWidget(self.group_backends, 1)

        self.group_models = QtWidgets.QGroupBox("可用模型（双击后端 / 选择并切换模型）")
        gmv = QtWidgets.QVBoxLayout(self.group_models)
        self.list_models = QtWidgets.QListWidget()
        gmv.addWidget(self.list_models, 1)
        self.btn_use = make_pill_button("切换模型")
        self.btn_use.clicked.connect(self._on_use_model)
        gmv.addWidget(self.btn_use)
        v.addWidget(self.group_models, 2)

        self.runtime.status_changed.connect(self._on_status)
        QtCore.QTimer.singleShot(50, lambda: self._on_status(self.runtime.get_status()))
        self.list_backends.itemDoubleClicked.connect(self._on_pick_backend)

    def _on_status(self, st: dict):
        b = st.get("backend") or "auto"
        m = st.get("model") or "—"
        self.lbl_backend.setText(f"后端：{b}")
        self.lbl_model.setText(f"模型：{m}")

        self.list_backends.clear()
        for name, info in (st.get("backends") or {}).items():
            alive = "✅" if info.get("alive") else "❌"
            url = info.get("url") or info.get("note", "")
            it = QtWidgets.QListWidgetItem(f"{alive} {name}   {url}")
            it.setData(Qt.ItemDataRole.UserRole, name)
            self.list_backends.addItem(it)

        self._populate_models(b, st)

    def _populate_models(self, backend_name: str, st: dict):
        self.list_models.clear()
        models = (st.get("models") or {}).get(backend_name, [])
        if not models and backend_name == "auto":
            for bk, arr in (st.get("models") or {}).items():
                for m in arr:
                    it = QtWidgets.QListWidgetItem(f"[{bk}] {m.get('name')}")
                    it.setData(Qt.ItemDataRole.UserRole, (bk, m.get("name")))
                    self.list_models.addItem(it)
            return

        for m in models:
            it = QtWidgets.QListWidgetItem(m.get("name"))
            it.setData(Qt.ItemDataRole.UserRole, (backend_name, m.get("name")))
            self.list_models.addItem(it)

    def _on_pick_backend(self, item: QtWidgets.QListWidgetItem):
        bk = item.data(Qt.ItemDataRole.UserRole)
        self.runtime.set_backend(bk)
        self._populate_models(bk, self.runtime.get_status())

    def _on_use_model(self):
        it = self.list_models.currentItem()
        if not it:
            QtWidgets.QMessageBox.information(self, "提示", "请选择一个模型")
            return
        bk, name = it.data(Qt.ItemDataRole.UserRole)
        self.runtime.set_backend(bk)
        # 实际切换由 MainWindow 的 _bootstrap_llm 来做；这里只同步状态
        self.runtime.current_model = name
        self.runtime.status_changed.emit(self.runtime.get_status())
        QtWidgets.QMessageBox.information(self, "提示", f"已选择模型：{bk} / {name}\n如需真正切换，请在聊天或启动引导里执行 ai.set_model。")

class NetworkMonitor(QtCore.QObject):
    status_changed = QtCore.pyqtSignal(bool)

    def __init__(self, interval_ms=2500):
        super().__init__()
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._probe)
        self._force_offline = False
        self._timer.start()

    def set_force_offline(self, v: bool):
        self._force_offline = v
        self.status_changed.emit(not self._force_offline and self._quick_probe())

    def _quick_probe(self) -> bool:
        try:
            with socket.create_connection(("1.1.1.1", 53), timeout=0.8):
                return True
        except OSError:
            return False

    def _probe(self):
        self.status_changed.emit(False if self._force_offline else self._quick_probe())

# ========== 主窗口 ==========
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, system_context):
        super().__init__()
        self.ctx = system_context
        self.setWindowTitle("三花聚顶 · 聚核助手（无思考过程优化版）")
        self.setGeometry(100, 100, 1400, 860)

        self.tts_enabled = True

        # AICore 直连（兜底）
        self.ac = get_aicore_instance() if get_aicore_instance else None
        from core.gui_bridge.gui_memory_bridge import install_memory_pipeline as _gui_install_memory_pipeline
        _gui_install_memory_pipeline(self.ac, logger=self.append_log)  # SANHUA_GUI_MEMORY_PIPELINE_CALL
        self.runtime = ModelRuntime(self.ctx, ac=self.ac)

        # dispatcher 选择（真实环境优先）
        self.dispatcher = getattr(self.ctx, "action_dispatcher", None) or real_dispatcher

        self._init_ui()

        # 路由器（关键）
        self.router = ActionRouter(
            call_action=self._safe_call_action,
            list_actions=self._list_actions,
            dispatcher_obj=self.dispatcher,
            log=self.append_log,
        )

        self._install_refresh_timer()
        self.refresh_modules()

        self._network = NetworkMonitor()
        self._network.status_changed.connect(self._on_net)
        self._update_status_suffix(False)

        self._create_menus()

        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+K"), self, self.open_palette)
        QtGui.QShortcut(QtGui.QKeySequence("F5"), self, self.refresh_modules)

        self._bootstrap_llm()

        self.append_log(f"🧾 运行平台：{platform_display()}")
        if _INTENT_ERR:
            self.append_log("ℹ️ Intent 组件未接入（可忽略）。如需启用意图识别，请检查 IntentRecognizer/ActionSynthesizer 导入路径。")

    def _init_ui(self):
        central = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(central)
        h.setSpacing(16)

        # 左：模块 + 模型中心
        left = QtWidgets.QFrame()
        lv = QtWidgets.QVBoxLayout(left)
        lv.setSpacing(12)

        self.status_capsule = QtWidgets.QFrame()
        self.status_capsule.setObjectName("status_capsule")
        sv = QtWidgets.QHBoxLayout(self.status_capsule)
        sv.setContentsMargins(10, 6, 10, 6)
        self.lbl_title = QtWidgets.QLabel("三花聚顶 · 聚核助手")
        self.lbl_title.setStyleSheet("font-weight:600; letter-spacing:0.5px;")
        self.badge_online = QtWidgets.QLabel("● 离线")
        self.badge_online.setStyleSheet("color:#f0a500;")
        self.badge_health = QtWidgets.QLabel("健康：未知")
        self.badge_health.setStyleSheet(f"color:{Theme.SUB};")
        sv.addWidget(self.lbl_title)
        sv.addStretch()
        sv.addWidget(self.badge_health)
        sv.addSpacing(16)
        sv.addWidget(self.badge_online)
        lv.addWidget(self.status_capsule)

        mod_group = QtWidgets.QGroupBox("模块管理")
        mv = QtWidgets.QVBoxLayout(mod_group)
        self.table = ModuleTable(owner_getter=lambda: self)
        mv.addWidget(self.table, 1)
        mod_btns = QtWidgets.QHBoxLayout()
        self.btn_start = make_pill_button("启动全部")
        self.btn_stop = make_pill_button("停止全部")
        self.btn_restart_all = make_pill_button("重启全部")
        self.btn_refresh = make_pill_button("刷新")
        for b in [self.btn_start, self.btn_stop, self.btn_restart_all, self.btn_refresh]:
            mod_btns.addWidget(b)
        mv.addLayout(mod_btns)
        lv.addWidget(mod_group, 2)

        self.model_center = ModelCenter(self.runtime)
        lv.addWidget(self.model_center, 3)

        # 中：聊天
        center = QtWidgets.QFrame()
        cv = QtWidgets.QVBoxLayout(center)
        self.chat_panel = ChatPanel(self.handle_user_message, self.set_tts_enabled)
        cv.addWidget(self.chat_panel)

        # 右：调用链 + 日志 + 控制开关
        right = QtWidgets.QFrame()
        rv = QtWidgets.QVBoxLayout(right)
        rv.setSpacing(12)

        chain_group = QtWidgets.QGroupBox("调用链可视化")
        cgv = QtWidgets.QVBoxLayout(chain_group)
        self.chain = ActionChainView()
        self.chain.setMinimumHeight(160)
        cgv.addWidget(self.chain)
        rv.addWidget(chain_group, 1)

        log_group = QtWidgets.QGroupBox("运行日志")
        lgv = QtWidgets.QVBoxLayout(log_group)
        self.logs = QtWidgets.QTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMinimumHeight(120)
        lgv.addWidget(self.logs, 1)

        # 控制按钮区（关键：自动动作开关）
        btns = QtWidgets.QHBoxLayout()
        self.btn_palette = make_pill_button("命令面板 Ctrl+K", minw=160)
        self.btn_auto_action = make_pill_button("自动动作：关", minw=140)
        self.btn_auto_action.setCheckable(True)
        self.btn_auto_action.setChecked(False)
        self.btn_auto_action.toggled.connect(self._toggle_auto_action)

        btns.addWidget(self.btn_palette)
        btns.addWidget(self.btn_auto_action)
        btns.addStretch()
        lgv.addLayout(btns)

        rv.addWidget(log_group, 1)

        h.addWidget(left, 4)
        h.addWidget(center, 6)
        h.addWidget(right, 4)
        self.setCentralWidget(central)

        self.left_panel = left
        self.right_panel = right

        # Docks
        self.sysmon_dock = SystemMonitorDock(self.ctx, self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.sysmon_dock)
        self.sysmon_dock.hide()

        self.avatar_dock = AvatarDock(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.avatar_dock)
        self.avatar_dock.hide()

        self.memory_dock = None
        mm = None
        if self.ac:
            if hasattr(self.ac, "memory_manager"):
                mm = getattr(self.ac, "memory_manager")
            elif hasattr(self.ac, "memory_engine"):
                mm = getattr(self.ac, "memory_engine")
        if MemoryDock and mm:
            try:
                self.memory_dock = MemoryDock(mm, self)
                self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.memory_dock)
                self.memory_dock.hide()
            except Exception as e:
                self.append_log(f"❌ 记忆中心初始化失败：{e}")

        self.btn_start.clicked.connect(self.start_all)
        self.btn_stop.clicked.connect(self.stop_all)
        self.btn_restart_all.clicked.connect(self.restart_all)
        self.btn_refresh.clicked.connect(self.refresh_modules)
        self.btn_palette.clicked.connect(self.open_palette)

        self._try_load_aliases()

    def _create_menus(self):
        menubar = self.menuBar()
        m_file = menubar.addMenu("文件")
        act_quit = QtGui.QAction("退出", self)
        act_quit.triggered.connect(self.close)
        m_file.addAction(act_quit)

        m_view = menubar.addMenu("视图")
        act_sysmon = QtGui.QAction("📊 系统监控", self, checkable=True, checked=False)
        act_sysmon.toggled.connect(lambda v: self.sysmon_dock.setVisible(v))
        m_view.addAction(act_sysmon)

        act_avatar = QtGui.QAction("🎭 虚拟形象", self, checkable=True, checked=False)
        act_avatar.toggled.connect(lambda v: self.avatar_dock.setVisible(v))
        m_view.addAction(act_avatar)

        if self.memory_dock:
            act_mem = QtGui.QAction("🧠 记忆中心", self, checkable=True, checked=False)
            act_mem.toggled.connect(lambda v: self.memory_dock.setVisible(v))
            m_view.addAction(act_mem)

        m_tools = menubar.addMenu("工具")
        act_hint = QtGui.QAction("动作提示", self)
        act_hint.triggered.connect(lambda: QtWidgets.QMessageBox.information(
            self, "动作提示",
            "聊天默认不执行动作。\n\n"
            "1) 显式动作：输入 /锁屏 或 !shutdown\n"
            "2) 自动动作：右侧开关打开后，可用自然语言触发（仍会阻止危险动作误触发）\n"
            "3) Ctrl+K：命令面板手动执行动作"
        ))
        m_tools.addAction(act_hint)

    def _toggle_auto_action(self, enabled: bool):
        self.router.set_auto_action(enabled)
        self.btn_auto_action.setText(f"自动动作：{'开' if enabled else '关'}")
        self.append_log(f"⚙️ 自动动作已{'开启' if enabled else '关闭'}：{'alias→intent→chat' if enabled else 'chat only'}")

    def _install_refresh_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self.refresh_modules)
        self._timer.start()

    def set_tts_enabled(self, v: bool):
        self.tts_enabled = v
        if not v and self._has_action("tts.stop"):
            self._safe_call_action("tts.stop", {})

    # 替换原有的 _strip_think_block 函数
    def _strip_llm_protocol(self, text: str) -> str:
        """清除所有协议标记和思考过程"""
        return _strip_llm_protocol(text)

    def _safe_call_action(self, name, params=None):
        try:
            return self.ctx.call_action(name, params=params or {})
        except Exception as e:
            # 这里把你遇到的 debug() 参数错误做可观测化
            msg = f"{name} 执行异常：{e}"
            tb = traceback.format_exc()
            if "debug() takes" in str(e) and "positional arguments" in str(e):
                msg += "\n（提示：某模块的 debug() 自定义封装签名不兼容 logging 风格调用；需要把 debug 改成支持 *args 或替换为 logging.debug）"
            self.append_log("❌ " + msg)
            self.append_log(tb.splitlines()[-1] if tb else "")
            QtWidgets.QMessageBox.warning(self, "动作失败", msg)
            return {"ok": False, "error": str(e), "traceback": tb}

    def _list_actions(self):
        def _canon(acts):
            if isinstance(acts, dict):
                return [{"name": k, **(v or {})} for k, v in acts.items()]
            if isinstance(acts, list):
                if acts and isinstance(acts[0], str):
                    return [{"name": n} for n in acts]
                return acts
            return []

        try:
            if self.ctx and hasattr(self.ctx, "list_actions"):
                return _canon(self.ctx.list_actions(detailed=True))
        except Exception:
            pass

        # fallback：兼容无标准 context 的旧运行态，不再直摸 ctx.action_dispatcher。
        disp = self.dispatcher
        try:
            if disp and hasattr(disp, "list_actions"):
                return _canon(disp.list_actions(detailed=True))
        except Exception:
            pass
        return []

    def _has_action(self, name: str) -> bool:
        return _action_name_in_list(self._list_actions(), name)

    def open_palette(self):
        dlg = CommandPalette(self._list_actions, self)

        def _on(a: dict):
            name = a.get("name")
            if not name:
                return
            test = QtWidgets.QMessageBox.question(
                self,
                "执行动作",
                f"要测试动作 {name} 吗？\n（'是'打开参数窗口，'否'直接无参执行）",
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            )
            if test == QtWidgets.QMessageBox.StandardButton.Yes:
                d = ActionRunnerDialog(name, self._safe_call_action, self)
                d.exec()
                self.chain.show_chain(["User", "Palette", f"Action:{name}", "Done"], True)
            else:
                res = self._safe_call_action(name, params={})
                self.append_log(f"▶ {name} -> {self._fmt(res)}")
                self.chain.show_chain(["User", "Palette", f"Action:{name}", "Done"], True)

        dlg.triggered.connect(_on)
        dlg.exec()

    def _json_safe(self, obj, _seen=None):
        if _seen is None:
            _seen = set()
        obj_id = id(obj)
        if obj_id in _seen:
            return "[circular]"
        _seen.add(obj_id)
        if obj is None or isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, bytes):
            try:
                return obj.decode("utf-8", errors="replace")
            except Exception:
                return repr(obj)
        if isinstance(obj, dict):
            return {str(k): self._json_safe(v, _seen) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)):
            return [self._json_safe(v, _seen) for v in obj]
        if hasattr(obj, "__dict__"):
            try:
                data = {}
                for k, v in obj.__dict__.items():
                    if k.startswith("_"):
                        continue
                    if callable(v):
                        continue
                    data[str(k)] = self._json_safe(v, _seen)
                if data:
                    return data
            except Exception:
                pass
        return repr(obj)

    def _fmt(self, obj):
        if isinstance(obj, str):
            return obj
        try:
            safe_obj = self._json_safe(obj)
            return json.dumps(safe_obj, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"[format_error] {e}: {repr(obj)}"

    def refresh_modules(self):
        try:
            health = self._safe_call_action("system.health_check")
            modules = health.get("modules", {}) if isinstance(health, dict) else {}
            raw_status = (health.get("status") if isinstance(health, dict) else None) or "UNKNOWN"
            raw_health = (health.get("health") if isinstance(health, dict) else None) or raw_status
            zh2, color2 = translate_health(raw_health)
            self.table.update_modules(modules)
            self.badge_health.setText(f"健康：{zh2}")
            self.badge_health.setStyleSheet(f"color:{color2};")
        except Exception as e:
            self.append_log(f"系统状态获取失败：{e}")

    def _bootstrap_llm(self):
        if not _LLM_ACTIONS_READY:
            self.append_log("⚠️ ai.* 动作尚未就绪（engine_compat 或 register_actions 未加载），继续使用 AICore 兜底。")
            return

        # 尝试绑定 llama.cpp
        if self._has_action("ai.use_llamacpp"):
            self._safe_call_action("ai.use_llamacpp", {})
        else:
            self.append_log("⚠️ ai.use_llamacpp 未注册，跳过启动期绑定。")
        model_env = os.getenv("SANHUA_ACTIVE_MODEL") or os.path.basename(os.getenv("SANHUA_MODEL", "llama3-8b.gguf"))
        if self._has_action("ai.set_model"):
            self._safe_call_action("ai.set_model", {"name": model_env})
        else:
            self.append_log("⚠️ ai.set_model 未注册，跳过启动期模型选择。")
        self.append_log(f"🧠 LLM 就绪：llamacpp / {model_env}")

    def _try_load_aliases(self):
        try:
            from pathlib import Path as _Path

            root = _Path(__file__).resolve().parents[2]
            plat = detect_platform_key()
            base = root / "config" / "aliases.yaml"
            plat_file = root / "config" / f"aliases.{plat}.yaml"

            disp = self.dispatcher
            if not disp:
                self.append_log("⚠️ dispatcher 不可用，跳过 aliases 加载")
                return

            def _alias_count(_d):
                if hasattr(_d, "get_all_aliases"):
                    try:
                        _aliases = _d.get_all_aliases()
                        if isinstance(_aliases, dict):
                            return len(_aliases)
                    except Exception:
                        pass
                _action_aliases = getattr(_d, "_action_aliases", None)
                if isinstance(_action_aliases, dict):
                    return len(_action_aliases)
                for _attr in ("aliases", "_aliases", "alias_map", "_alias_map"):
                    _v = getattr(_d, _attr, None)
                    if isinstance(_v, dict):
                        return len(_v)
                return 0

            existing = _alias_count(disp)

            if getattr(self.ctx, "_aliases_loaded", False) and existing > 0:
                self.append_log(f"🌸 aliases already loaded = {existing} (platform={plat})")
                return

            total = 0
            if base.exists():
                total += int(load_aliases_from_yaml(str(base), disp) or 0)
            if plat_file.exists():
                total += int(load_aliases_from_yaml(str(plat_file), disp) or 0)

            final_count = _alias_count(disp)

            if total > 0 or final_count > 0:
                try:
                    setattr(self.ctx, "_aliases_loaded", True)
                except Exception:
                    pass
                self.append_log(f"🌸 aliases loaded = {max(total, final_count)} (platform={plat})")
            else:
                self.append_log(
                    f"⚠️ aliases 未加载（未找到 {base} 或 {plat_file}，或 loader 返回 0）"
                )

        except Exception as e:
            self.append_log(f"❌ alias 加载失败：{pretty_exc(e)}")

    def _chat_via_actions(self, user_text: str) -> str:
        """
        聊天优先级：
        0) 本地记忆短路（身份 / 刚才说了什么）
        1) ai.chat（正式主聊天桥）
        2) AICore.chat（内部 / 兜底桥）
        3) aicore.chat（历史 action 兜底）
        4) AICore.ask（保留探测分支，不作为默认第一跳）
        5) 本地记忆兜底

        GUI 主入口不再长期维护内联聊天编排主流程。
        具体聊天编排唯一真相源收口到 core.gui_bridge.chat_orchestrator.GUIChatOrchestrator。
        """
        from core.gui_bridge.chat_orchestrator import GUIChatOrchestrator

        _orchestrator = GUIChatOrchestrator(
            ctx=getattr(self, "ctx", None),
            aicore=getattr(self, "ac", None),
            action_caller=lambda _name, _payload: self._safe_call_action(_name, _payload),
            list_actions=self._list_actions,
            logger=self.append_log,
            strip_protocol=self._strip_llm_protocol,
        )
        return _orchestrator.handle_chat(user_text)

    def _speak_if_enabled(self, text: str):
        if not self.tts_enabled:
            return

        try:
            clean_text = self._strip_llm_protocol(text)
            acts = self._list_actions()
            if any(a.get("name") == "tts.speak" for a in acts):
                self._safe_call_action("tts.speak", {"text": clean_text, "lang": "zh"})
                self.append_log("🔊 [TTS] 已自动播报")
            else:
                self.append_log("⚠️ [TTS] 模块未加载")
        except Exception as e:
            self.append_log(f"❌ TTS 失败：{e}")

    # === SANHUA_GUI_CHAT_ROUTE_PRIORITY_V1_END ===

    def handle_user_message(self, text: str):
        self.append_log(f"🧑‍💻 用户: {text}")

        # 路由：决定走动作还是走聊天
        r = self.router.route(text)

        if r.chain_steps:
            self.chain.show_chain(r.chain_steps, True, 150)
        else:
            self.chain.show_chain(["User", "Route", "Done"], True, 150)

        # 1) 执行动作（若命中）
        if r.kind == "action" and r.action_name:
            self.append_log(f"▶ {r.action_name} (params={r.action_params or {}})")
            if r.action_name == "play_music":
                try:
                    _disp = getattr(self.ctx, "action_dispatcher", None)
                    _meta = getattr(getattr(_disp, "_actions", {}), "get", lambda *_: None)("play_music")
                    _mod = getattr(_meta, "module", None)
                    _func = getattr(_meta, "func", None)
                    _qname = getattr(_func, "__qualname__", None) or getattr(_func, "__name__", None)
                    self.append_log(f"🔎 play_music meta: module={_mod} func={_qname}")
                except Exception as _e:
                    self.append_log(f"🔎 play_music meta: error={_e}")
            result = self._safe_call_action(r.action_name, r.action_params or {})
            if r.action_name == "play_music":
                self.append_log(f"🔎 play_music result type={type(result).__name__} repr={result!r}")
            r.action_result = result

            # 给用户一个可读回包（避免只看到 json）
            if isinstance(result, str):
                user_reply = result
            else:
                user_reply = self._fmt(result)

            # 对动作结果进行协议清洗
            user_reply = self._strip_llm_protocol(user_reply)
            
            self.chat_panel.add_bubble(user_reply, False)
            if r.action_name == "play_music":
                self.append_log(f"🔎 play_music user_reply={user_reply!r}")
            self.append_log(f"✅ ActionResult: {user_reply[:300]}")
            self._speak_if_enabled(user_reply if isinstance(user_reply, str) else "动作已执行")
            return

        # 2) 默认聊天
        reply = self._chat_via_actions(text)
        if not reply:
            reply = "（无回复）"

        self.chat_panel.add_bubble(reply, False)
        self.append_log(f"🤖 AI: {reply[:500]}...")
        self._speak_if_enabled(reply)

    def append_log(self, text: str):
        self.logs.append(text)
        self.logs.verticalScrollBar().setValue(self.logs.verticalScrollBar().maximum())

    # ---- 模块批量操作 ----
    def start_all(self):
        self.append_log("⏯️ 启动全部模块")
        try:
            self.ctx.module_manager.start_modules()
        finally:
            self.refresh_modules()

    def stop_all(self):
        self.append_log("⏹️ 停止全部模块")
        try:
            self.ctx.module_manager.stop_modules()
        finally:
            self.refresh_modules()

    def restart_all(self):
        self.append_log("🔄 重启全部模块")
        try:
            self.ctx.module_manager.stop_modules()
            self.ctx.module_manager.start_modules()
        finally:
            self.refresh_modules()

    def restart_module(self, mod):
        self.append_log(f"🔄 重启模块: {mod}")
        try:
            self.ctx.module_manager.restart_module(mod)
        finally:
            self.refresh_modules()

    def unload_module(self, mod):
        self.append_log(f"❌ 卸载模块: {mod}")
        try:
            self.ctx.module_manager.unload_module(mod)
        finally:
            self.refresh_modules()

    def _on_net(self, ok: bool):
        self._update_status_suffix(ok)

    def _update_status_suffix(self, online: bool):
        self.badge_online.setText("● 在线" if online else "● 离线")
        self.badge_online.setStyleSheet(f"color:{('#0f9150' if online else '#b58900')};")
        self.setWindowTitle(f"三花聚顶 · 聚核助手（无思考过程优化版） {'🌐 在线' if online else '🌐 离线'}")

# ====== 启动入口 ======
def main():
    if (FORCE_REAL_ENV or DISABLE_DEMO_FALLBACK) and not REAL_ENV:
        raise RuntimeError(
            "要求真实环境启动，但 REAL_ENV=False（真实环境导入失败）。\n"
            f"原始异常: {repr(_REAL_IMPORT_ERR)}\n"
            f"Traceback:\n{_REAL_IMPORT_TB}"
        )

    env_type = "真实环境" if REAL_ENV else "演示环境"
    print(f"🚀 启动三花聚顶 GUI - {env_type}")
    if not REAL_ENV and _REAL_IMPORT_TB:
        print("⚠️ 真实环境导入失败，已降级演示环境。真实异常如下：")
        print(_REAL_IMPORT_TB)

    enable_hidpi_safely()

    # 1) SystemContext
    context = create_system_context(entry_mode="gui")

    # === SANHUA_BOOTSTRAP_ACTIONS_AND_ALIASES ===
    try:
        # 统一单例 dispatcher
        from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER
        # 关键：先把动作注册进 ACTION_MANAGER（否则 alias/intent 命中也执行不了）
        from core.aicore.action_manager import ActionMapper
        from utils.alias_loader import load_aliases_from_yaml

        # 给 dispatcher 注入 context（动作里若用到 ctx/event_bus 会需要）
        try:
            ACTION_MANAGER.set_context(context)
        except Exception:
            pass

        if not getattr(context, "_aicore_actions_registered", False):
            class _DummyCore: pass
            ActionMapper(getattr(context, "aicore", None) or _DummyCore())
            context._aicore_actions_registered = True
            print("✅ actions registered into ACTION_MANAGER")
            # === SANHUA_GUI_LLM_READY_MARKER_V1 START ===
            try:
                import os as _sanhua_gui_os

                _backend = (
                    _sanhua_gui_os.getenv("SANHUA_LLM_BACKEND")
                    or _sanhua_gui_os.getenv("AICORE_LLM_BACKEND")
                    or "unknown"
                ).strip()

                _model = (
                    _sanhua_gui_os.getenv("SANHUA_ACTIVE_MODEL")
                    or _sanhua_gui_os.getenv("SANHUA_MODEL")
                    or _sanhua_gui_os.getenv("SANHUA_MODEL_NAME")
                    or _sanhua_gui_os.getenv("SANHUA_LLAMA_MODEL")
                    or ""
                ).strip()

                _base_url = (
                    _sanhua_gui_os.getenv("SANHUA_LLAMA_BASE_URL")
                    or _sanhua_gui_os.getenv("SANHUA_SERVER")
                    or _sanhua_gui_os.getenv("OPENAI_BASE_URL")
                    or ""
                ).strip()

                if _model and _base_url:
                    print(f"🧠 LLM 就绪：{_backend} / {_model} / {_base_url}")
                elif _model:
                    print(f"🧠 LLM 就绪：{_backend} / {_model}")
                elif _base_url:
                    print(f"🧠 LLM 就绪：{_backend} / {_base_url}")
                else:
                    print(f"🧠 LLM 就绪：{_backend}")
            except Exception as _e:
                print(f"⚠️ LLM readiness marker emit failed: {_e}")
            # === SANHUA_GUI_LLM_READY_MARKER_V1 END ===

        # aliases 在动作之后加载（顺序保证）
        if not getattr(context, "_aliases_loaded", False):
            total = 0
            total += int(load_aliases_from_yaml("config/aliases.yaml", ACTION_MANAGER) or 0)
            import sys, os
            plat = sys.platform.lower()
            pf = f"config/aliases.{plat}.yaml"
            if os.path.exists(pf):
                total += int(load_aliases_from_yaml(pf, ACTION_MANAGER) or 0)
            context._aliases_loaded = True
            print(f"🌸 aliases loaded = {total} (platform={plat})")
    except Exception as e:
        print("⚠️ bootstrap actions/aliases failed:", e)


    # 2) ModuleManager（若未挂载则挂）
    if not getattr(context, "module_manager", None):
        modules_dir = context.get_config("modules_dir", "modules") if hasattr(context, "get_config") else "modules"
        try:
            context.module_manager = ModuleManager(modules_dir, context)
            context.module_manager.load_modules_metadata()
            context.module_manager.load_modules("gui")
            context.module_manager.start_modules()
        except Exception as e:
            print(f"模块管理器初始化失败: {e}")

    # 3) call_action 兼容绑定（演示模式需要）
    if not hasattr(context, "call_action"):
        def call_action(name, params=None):
            disp = getattr(context, "action_dispatcher", None) or real_dispatcher
            return disp.execute(name, params=params or {})
        context.call_action = call_action

    # 4) 启动 Qt
    app = QtWidgets.QApplication(sys.argv)
    if sys.platform == "darwin":
        font = QtGui.QFont("PingFang SC", 12)
    elif sys.platform == "win32":
        font = QtGui.QFont("Microsoft YaHei", 10)
    else:
        font = QtGui.QFont("Noto Sans SC", 11)
    app.setFont(font)
    Theme.apply(app)

    win = MainWindow(context)
    win.show()
    sys.exit(app.exec())


# GUI memory pipeline/local memory logic lives in core.gui_bridge.gui_memory_bridge.



if __name__ == "__main__":
    main()
