#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三花聚顶 · tts_module 语音播报模块（标准化热插拔+云本地双通道极致版）
- 统一的 BaseModule 实现（包含 handle_event）
- 动作集合：tts.start / tts.stop / tts.health / tts.speak / tts.engine.switch
- 云端优先（edge_tts），本地兜底（piper / espeak-ng / espeak / spd-say / festival）
- 线程安全（后台播放）、事件驱动（支持 event_bus→"tts.speak"）
"""

from __future__ import annotations
import os
import subprocess
import threading
import tempfile
import time
import uuid
from typing import Optional, Dict, Any

try:
    import edge_tts  # 云端TTS（可选）
except ImportError:
    edge_tts = None

from core.core2_0.sanhuatongyu.module.base import BaseModule
from core.core2_0.sanhuatongyu.logger import get_logger
from core.core2_0.sanhuatongyu.action_dispatcher import dispatcher as ACTION_DISPATCHER

logger = get_logger("tts_module")

# ---------------- 工具函数 ----------------
def _which(cmd: str) -> bool:
    return subprocess.call(['which', cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0

def find_local_tts_engine() -> Optional[str]:
    for tts in ['piper', 'espeak-ng', 'espeak', 'spd-say', 'festival']:
        if _which(tts):
            return tts
    return None

# ---------------- 模块实现 ----------------
class TTSModule(BaseModule):
    VERSION = "2.4.0"

    def __init__(self, meta=None, context=None):
        super().__init__(meta, context)
        # 配置
        cfg = getattr(meta, "config", {}) if meta else {}
        self.prefer_cloud: bool = bool(cfg.get("prefer_cloud", True))
        self.piper_model_path: str = cfg.get("piper_model_path", "")  # 可在 manifest 配置
        self.player_for_cloud: str = cfg.get("cloud_player", "mpv")   # 播放 cloud mp3
        self.player_args: list[str] = cfg.get("cloud_player_args", ["--no-terminal"])

        # 状态
        self.local_engine: Optional[str] = find_local_tts_engine()
        self.cloud_enabled: bool = bool(edge_tts)
        self._actions_registered = False
        self._running = False
        self._lock = threading.RLock()
        self._play_token = 0
        self._current_process: Optional[subprocess.Popen] = None
        self._current_thread: Optional[threading.Thread] = None
        self.last_engine: Optional[str] = None

        logger.info(
            f"TTS init | prefer_cloud={self.prefer_cloud} "
            f"cloud_enabled={self.cloud_enabled} local_engine={self.local_engine}"
        )

    # ----------- BaseModule 标准生命周期 -----------
    def preload(self):
        self._register_actions()
        # 事件总线订阅（可选）
        bus = getattr(self.context, "event_bus", None)
        if bus:
            bus.subscribe("tts.speak", self._on_bus_tts_speak)
        logger.info("TTS preload 完成")

    def setup(self):
        logger.info("TTS setup 完成")

    def start(self):
        with self._lock:
            self._running = True
        logger.info("TTS模块已启动")

    def stop(self):
        with self._lock:
            self._running = False
            self._play_token += 1
            self._stop_current_process_locked()
        logger.info("TTS模块已停止")

    def cleanup(self):
        self.stop()
        # 反注册动作（可选）
        try:
            ACTION_DISPATCHER.unregister_action("tts.speak")
            ACTION_DISPATCHER.unregister_action("tts.start")
            ACTION_DISPATCHER.unregister_action("tts.stop")
            ACTION_DISPATCHER.unregister_action("tts.health")
            ACTION_DISPATCHER.unregister_action("tts.engine.switch")
        except Exception:
            pass
        logger.info("TTS清理完成")

    # ----------- 抽象方法：必须实现 -----------
    def handle_event(self, event_type: str, data: Optional[Dict[str, Any]] = None):
        """
        模块管理器会通过此入口派发事件。
        这里做一个统一桥接：仅处理我们关心的事件类型。
        """
        if event_type == "tts.speak":
            params = data or {}
            text = params.get("text", "")
            lang = params.get("lang", "zh")
            cloud = params.get("cloud", None)
            return self.speak(text, lang=lang, cloud=cloud)
        # 其他事件不处理则返回 None
        return None

    # ----------- 事件总线回调（可选）-----------
    def _on_bus_tts_speak(self, event_name, data=None):
        # 与 handle_event 语义一致
        self.handle_event("tts.speak", data)

    # ----------- 对外：健康状态 -----------
    def health_check(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "status": "READY" if self._running else "OK",
                "version": self.VERSION,
                "cloud_enabled": self.cloud_enabled,
                "local_engine": self.local_engine or "",
                "prefer_cloud": self.prefer_cloud,
                "last_engine": self.last_engine or "",
                "speaking": self._current_process is not None and self._current_process.poll() is None,
            }

    # ----------- 主能力：播报 -----------
    def speak(self, text: str, lang: str = "zh", cloud: Optional[bool] = None, **kwargs):
        if not text:
            return {"status": "fail", "msg": "播报内容不能为空"}

        use_cloud = self.cloud_enabled and (self.prefer_cloud if cloud is None else cloud)
        with self._lock:
            self._play_token += 1
            token = self._play_token
            self._stop_current_process_locked()

        # 优先云端
        if use_cloud:
            if not edge_tts:
                logger.warning("edge_tts 未安装，自动切换本地TTS。")
            else:
                thread = threading.Thread(target=self._run_cloud_tts, args=(text, lang, token), daemon=True)
                with self._lock:
                    self._current_thread = thread
                    self.last_engine = "cloud"
                thread.start()
                return {"status": "ok", "msg": "云端播报已开始"}

        # 本地兜底
        if self.local_engine:
            thread = threading.Thread(target=self._run_local_tts, args=(text, lang, token), daemon=True)
            with self._lock:
                self._current_thread = thread
                self.last_engine = self.local_engine
            thread.start()
            return {"status": "ok", "msg": f"本地({self.local_engine})播报已开始"}

        logger.error("未检测到任何可用TTS后端")
        return {"status": "fail", "msg": "未检测到可用TTS后端"}

    def _stop_current_process_locked(self):
        proc = self._current_process
        self._current_process = None
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=0.5)
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"TTS 当前播放停止失败: {e}")

    def _token_alive(self, token: int) -> bool:
        with self._lock:
            return token == self._play_token

    def _run_process(self, cmd, token: int, **kwargs) -> bool:
        if not self._token_alive(token):
            return False
        kwargs.pop("check", None)
        stdin_data = kwargs.pop("input", None)
        if stdin_data is not None:
            kwargs.setdefault("stdin", subprocess.PIPE)
        proc = subprocess.Popen(cmd, **kwargs)
        with self._lock:
            if token != self._play_token:
                try:
                    proc.terminate()
                except Exception:
                    pass
                return False
            self._current_process = proc
        try:
            if stdin_data is not None:
                proc.communicate(stdin_data)
            else:
                proc.wait()
            return self._token_alive(token)
        finally:
            with self._lock:
                if self._current_process is proc:
                    self._current_process = None

    # ----------- 本地 & 云端 实现 -----------
    def _run_local_tts(self, text: str, lang: str, token: int):
        try:
            eng = self.local_engine
            if eng == "piper":
                if not self.piper_model_path:
                    logger.error("piper 被选中但未配置 piper_model_path")
                    return
                out_file = os.path.join(tempfile.gettempdir(), f"tts_{uuid.uuid4().hex}.wav")
                if not self._run_process(
                    ['piper', '--model', self.piper_model_path, '--output_file', out_file, '--text', text],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
                ):
                    return
                # 播放：优先 aplay / paplay / ffplay
                for player in (["aplay", out_file], ["paplay", out_file], ["ffplay", "-nodisp", "-autoexit", out_file]):
                    if _which(player[0]):
                        self._run_process(player, token, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        break
            elif eng == "espeak-ng":
                self._run_process(['espeak-ng', '-v', lang, text], token, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif eng == "espeak":
                self._run_process(['espeak', '-v', lang, text], token, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif eng == "spd-say":
                self._run_process(['spd-say', '-l', lang, text], token, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif eng == "festival":
                self._run_process(['festival', '--tts'], token, input=text.encode('utf-8'),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            else:
                logger.warning("没有可用本地TTS后端")
        except Exception as e:
            logger.error(f"本地TTS播报异常: {e}")

    def _run_cloud_tts(self, text: str, lang: str, token: int):
        try:
            import asyncio
            async def async_speak():
                voice = "zh-CN-XiaoxiaoNeural" if lang.startswith("zh") else "en-US-AriaNeural"
                communicate = edge_tts.Communicate(text, voice=voice)
                out_file = os.path.join(tempfile.gettempdir(), f"tts_cloud_{uuid.uuid4().hex}.mp3")
                await communicate.save(out_file)
                if not self._token_alive(token):
                    return
                # 播放
                player = self.player_for_cloud if _which(self.player_for_cloud) else None
                if player:
                    self._run_process([player, out_file, *self.player_args], token,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                elif _which("ffplay"):
                    self._run_process(["ffplay", "-nodisp", "-autoexit", out_file], token,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    logger.warning("未找到可用播放器（mpv/ffplay），仅生成了音频文件：%s", out_file)
            asyncio.run(async_speak())
        except Exception as e:
            logger.error(f"云端TTS播报异常: {e}")

    # ----------- 动作注册 -----------
    def _register_actions(self):
        if self._actions_registered:
            return
        names = [a["name"] for a in ACTION_DISPATCHER.list_actions(detailed=True)]

        def _reg(name, func, desc):
            if name not in names:
                ACTION_DISPATCHER.register_action(
                    name=name, func=func, description=desc, permission="user", module="tts_module"
                )

        _reg("tts.speak",
             lambda context, params=None, **kw: self._act_speak(params, **kw),
             "文本转语音播报（自动切换本地/云端）")

        _reg("tts.start",
             lambda context, params=None, **kw: self._act_start(),
             "启动TTS模块（置为运行状态）")

        _reg("tts.stop",
             lambda context, params=None, **kw: self._act_stop(),
             "停止TTS模块（置为非运行状态）")

        _reg("tts.health",
             lambda context, params=None, **kw: self.health_check(),
             "获取TTS模块健康状态")

        _reg("tts.engine.switch",
             lambda context, params=None, **kw: self._act_switch_engine(params or kw),
             "切换优先引擎（cloud/local）或设置 piper 模型路径")

        self._actions_registered = True
        logger.info("TTS 动作注册完成: tts.speak / tts.start / tts.stop / tts.health / tts.engine.switch")

    # ----------- 动作实现 -----------
    def _act_speak(self, params: Optional[Dict[str, Any]] = None, **kwargs):
        p = params or {}
        text = p.get("text") or kwargs.get("text") or ""
        lang = p.get("lang") or kwargs.get("lang") or "zh"
        cloud = p.get("cloud") if "cloud" in p else kwargs.get("cloud", None)
        return self.speak(text, lang=lang, cloud=cloud)

    def _act_start(self):
        self.start()
        return {"status": "ok", "running": True}

    def _act_stop(self):
        self.stop()
        return {"status": "ok", "running": False}

    def _act_switch_engine(self, params: Dict[str, Any]):
        # params: {"prefer": "cloud"|"local", "piper_model_path": "..."}
        pref = (params.get("prefer") or "").lower()
        if pref in ("cloud", "local"):
            self.prefer_cloud = (pref == "cloud")
        if "piper_model_path" in params:
            self.piper_model_path = params.get("piper_model_path") or self.piper_model_path
        # 更新本地引擎探测
        self.local_engine = find_local_tts_engine()
        return {
            "status": "ok",
            "prefer_cloud": self.prefer_cloud,
            "local_engine": self.local_engine,
            "piper_model_path": self.piper_model_path,
        }

# 供模块加载器反射
MODULE_CLASS = TTSModule
