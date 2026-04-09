#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三花聚顶 · voice_input 语音采集模块（平台版，稳定规约）
- 避免 dataclass（修复 Py3.13 动态加载崩溃）
- EnterpriseLogger 只接收单字符串：全部使用 f-string
- 默认用户目录存储，自动回退，免权限问题
- 动作：voice.start / voice.stop / voice.pause / voice.resume / voice.save / voice.status / voice.record_until_silence
"""

import os
import time
import wave
import queue
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List, Literal

# 平台基座
from core.core2_0.sanhuatongyu.module.base import BaseModule
from core.core2_0.sanhuatongyu.logger import get_logger
from core.core2_0.sanhuatongyu.action_dispatcher import dispatcher as ACTION_DISPATCHER

# 软依赖
try:
    import pyaudio  # type: ignore
except Exception:
    pyaudio = None
try:
    import numpy as np  # type: ignore
except Exception:
    np = None

log = get_logger("voice_input")

# --------- 配置默认值（用户目录，免 root）---------
DEFAULT_OUTPUT_DIR = str(Path.home() / ".local/share/voice_input/recordings")
DEFAULT_LOG_DIR = str(Path.home() / ".local/state/voice_input/logs")

DEFAULT_CONFIG: Dict[str, Any] = {
    "rate": 16000,
    "chunk": 1024,
    "channels": 1,
    "silence_threshold": 500,
    "max_silence_duration": 1.0,
    "max_recording_duration": 30.0,
    "noise_reduction_level": 0.7,
    "normalization": True,
    "output_dir": DEFAULT_OUTPUT_DIR,
    "log_dir": DEFAULT_LOG_DIR,
}

# --------- 简单状态类（替代 dataclass）---------
class AudioState:
    def __init__(self) -> None:
        self.is_recording: bool = False
        self.is_paused: bool = False
        self.duration: float = 0.0
        self.frames_count: int = 0
        self.last_audio_time: float = 0.0
        self.error: Optional[str] = None
        self.cpu_usage: float = 0.0
        self.memory_usage: int = 0

# --------- 语音核心 ---------
class VoiceInputCore:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.cfg = dict(DEFAULT_CONFIG)
        if config:
            self.cfg.update(config)

        self._pya = None
        self._stream = None
        self._frames: List[bytes] = []
        self._q: "queue.Queue[bytes|Exception]" = queue.Queue(maxsize=100)
        self._rec_evt = threading.Event()
        self._pause_evt = threading.Event()
        self._thr: Optional[threading.Thread] = None
        self._start_ts: Optional[float] = None
        self._lock = threading.Lock()
        self.state = AudioState()

        self._prepare_dirs()
        self._init_audio()

        log.info(f"VoiceInputCore 初始化完成（PyAudio={bool(self._pya)}, NumPy={bool(np)}）")

    # 目录准备（多级回退）
    def _prepare_dirs(self) -> None:
        outdir = Path(self.cfg.get("output_dir") or DEFAULT_OUTPUT_DIR)
        try:
            outdir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            # 回退至项目本地 data 目录
            fallback = Path.cwd() / "data" / "recordings"
            try:
                fallback.mkdir(parents=True, exist_ok=True)
                self.cfg["output_dir"] = str(fallback)
                log.info(f"无权限创建输出目录，已回退到本地目录：{fallback}")
            except Exception as e:
                msg = f"无法创建任何可写输出目录：{e}"
                log.error(msg)
                raise RuntimeError(msg)

        # 日志目录仅用于文件持久化（平台已有日志，这里可忽略失败）
        logdir = Path(self.cfg.get("log_dir") or DEFAULT_LOG_DIR)
        try:
            logdir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def _init_audio(self) -> None:
        if pyaudio is None:
            log.warning("PyAudio 未安装，录音相关动作可用性受限")
            return
        try:
            self._pya = pyaudio.PyAudio()
        except Exception as e:
            self._pya = None
            self.state.error = str(e)
            log.error(f"PyAudio 初始化失败：{e}")
            raise

    def _preprocess(self, data: bytes) -> bytes:
        if not data or np is None:
            return data
        try:
            arr = np.frombuffer(data, dtype=np.int16)
            if arr.size == 0:
                return data
            rms = float(np.sqrt(np.mean(np.square(arr)))) if arr.size else 0.0
            thr = max(
                int(self.cfg["silence_threshold"] * self.cfg["noise_reduction_level"]),
                int(rms * 0.8)
            )
            arr = np.where(np.abs(arr) < thr, 0, arr)
            if self.cfg.get("normalization", True):
                mx = int(np.max(np.abs(arr))) if arr.size else 0
                if mx > 0:
                    arr = (arr * (32767 / mx)).astype(np.int16)
            return arr.tobytes()
        except Exception as e:
            log.error(f"音频预处理失败：{e}")
            return data

    # ------- 控制面 -------
    def start(self, duration: Optional[float] = None) -> None:
        if self._pya is None:
            raise RuntimeError("未安装/初始化 PyAudio，无法开始录音")
        if self._rec_evt.is_set():
            log.warning("录音已在进行中，忽略重复 start")
            return
        # 若旧线程未收尾，强制 stop
        if self._thr and self._thr.is_alive():
            self.stop()

        with self._lock:
            self._frames.clear()
            self._rec_evt.set()
            self._pause_evt.clear()
            self._start_ts = time.time()
            self.state = AudioState()
            self.state.is_recording = True

        try:
            self._stream = self._pya.open(
                format=pyaudio.paInt16,
                channels=int(self.cfg["channels"]),
                rate=int(self.cfg["rate"]),
                input=True,
                frames_per_buffer=int(self.cfg["chunk"]),
            )
            self._thr = threading.Thread(
                target=self._record_loop,
                args=(duration,),
                daemon=True,
                name="VoiceInput-RecordThread",
            )
            self._thr.start()
            cfg_show = {k: v for k, v in self.cfg.items() if k not in ("output_dir", "log_dir")}
            log.info(f"开始录音，配置：{cfg_show}")
        except Exception as e:
            self._rec_evt.clear()
            self.state.error = str(e)
            log.error(f"启动录音失败：{e}")
            raise

    def pause(self) -> None:
        if self._rec_evt.is_set():
            self._pause_evt.set()
            self.state.is_paused = True
            log.info("录音已暂停")

    def resume(self) -> None:
        if self._rec_evt.is_set():
            self._pause_evt.clear()
            self.state.is_paused = False
            log.info("录音已恢复")

    def stop(self) -> float:
        if not self._rec_evt.is_set():
            return 0.0
        self._rec_evt.clear()
        if self._thr and self._thr.is_alive():
            self._thr.join(timeout=2.0)
        if self._stream:
            try:
                if self._stream.is_active():
                    self._stream.stop_stream()
                self._stream.close()
            except Exception as e:
                log.error(f"关闭音频流失败：{e}")
            finally:
                self._stream = None
        dur = self.duration()
        with self._lock:
            self.state.is_recording = False
            self.state.duration = dur
        log.info(f"录音停止，时长 {dur:.2f}s，帧数 {len(self._frames)}")
        return dur

    def terminate(self) -> None:
        try:
            self.stop()
        finally:
            if self._pya:
                try:
                    self._pya.terminate()
                except Exception as e:
                    log.error(f"释放 PyAudio 资源失败：{e}")
                self._pya = None
            with self._lock:
                self._frames.clear()
        log.info("VoiceInputCore 资源释放完成")

    def duration(self) -> float:
        if not self._start_ts:
            return 0.0
        return (time.time() - self._start_ts) if self._rec_evt.is_set() else self.state.duration

    def frames(self) -> List[bytes]:
        with self._lock:
            return list(self._frames)

    def save_wav(self, filename: str) -> str:
        if not self._frames:
            raise ValueError("没有可保存的音频数据")
        outdir = Path(self.cfg["output_dir"])
        outdir.mkdir(parents=True, exist_ok=True)  # 此处基本不会再抛权限，因为前面已经回退过
        path = outdir / filename
        try:
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(int(self.cfg["channels"]))
                # 若无 PyAudio，用 2 字节宽度（16bit）
                sampwidth = self._pya.get_sample_size(pyaudio.paInt16) if self._pya else 2
                wf.setsampwidth(sampwidth)
                wf.setframerate(int(self.cfg["rate"]))
                with self._lock:
                    wf.writeframes(b"".join(self._frames))
            try:
                os.chmod(path, 0o644)
            except Exception:
                pass
            size_kb = os.path.getsize(path) / 1024.0
            log.info(f"WAV 保存成功：{path}（{size_kb:.1f} KB）")
            return str(path)
        except Exception as e:
            log.error(f"保存 WAV 失败：{e}")
            raise

    def record_until_silence(
        self,
        silence_threshold: Optional[int] = None,
        silence_duration: Optional[float] = None,
        max_duration: Optional[float] = None,
    ) -> float:
        thr = int(silence_threshold or self.cfg["silence_threshold"])
        max_sil = float(silence_duration or self.cfg["max_silence_duration"])
        max_rec = float(max_duration or self.cfg["max_recording_duration"])

        self.start()
        start = time.time()
        sil_start: Optional[float] = None
        last_audio = start
        log.info(f"静音检测录音开始：阈值={thr}，最大静音={max_sil}s，最长录音={max_rec}s")

        while self._rec_evt.is_set():
            try:
                buf = self._q.get(timeout=0.6)
                if isinstance(buf, Exception):
                    raise buf
                with self._lock:
                    self._frames.append(buf)
                    self.state.frames_count = len(self._frames)
                last_audio = time.time()

                if np is not None:
                    a = np.frombuffer(buf, dtype=np.int16)
                    amp = int(np.max(np.abs(a))) if a.size else 0
                else:
                    amp = 1000 if buf else 0

                if amp > thr:
                    sil_start = None
                else:
                    sil_start = sil_start or time.time()
                    if time.time() - sil_start >= max_sil:
                        log.info("检测到持续静音，停止录音")
                        break

                if time.time() - start >= max_rec:
                    log.info("已达最大录音时长，停止录音")
                    break
            except queue.Empty:
                if time.time() - last_audio >= max_sil:
                    log.info("长时间无音频输入，停止录音")
                    break
            except Exception as e:
                log.error(f"静音录音异常：{e}")
                break

        return self.stop()

    # 录音线程
    def _record_loop(self, duration: Optional[float]) -> None:
        st = time.time()
        while self._rec_evt.is_set():
            if self._pause_evt.is_set():
                time.sleep(0.05)
                continue
            try:
                data = self._stream.read(int(self.cfg["chunk"]), exception_on_overflow=False)
                processed = self._preprocess(data)
                try:
                    self._q.put_nowait(processed)
                except queue.Full:
                    try:
                        _ = self._q.get_nowait()
                    except Exception:
                        pass
                    self._q.put_nowait(processed)
                with self._lock:
                    self._frames.append(processed)
                    self.state.frames_count = len(self._frames)
                    self.state.last_audio_time = time.time()
                if duration and (time.time() - st) >= duration:
                    log.info("达到指定录音时长，停止录音")
                    self._rec_evt.clear()
            except Exception as e:
                try:
                    self._q.put_nowait(e)
                except Exception:
                    pass
                log.error(f"录音线程异常：{e}")
                self._rec_evt.clear()
            time.sleep(0.003)

# --------- 模块对接层 ---------
class VoiceInputModule(BaseModule):
    VERSION = "1.2.0"

    def __init__(self, meta=None, context=None) -> None:
        super().__init__(meta, context)
        self.core: Optional[VoiceInputCore] = None
        self._actions_registered = False
        self._init_ts = time.time()

    # 生命周期
    def preload(self) -> None:
        self._register_actions()

    def setup(self) -> None:
        cfg = (getattr(self.meta, "config", None) or {})
        self.core = VoiceInputCore(cfg)
        log.info(f"voice_input 模块初始化完成，版本 {self.VERSION}")

    def start(self) -> None:
        log.info(f"voice_input 模块已就绪（uptime={time.time() - self._init_ts:.2f}s）")

    def stop(self) -> None:
        if self.core:
            self.core.terminate()
        log.info("voice_input 模块已停止")

    def cleanup(self) -> None:
        self.stop()

    # 健康检查
    def health_check(self) -> Dict[str, Any]:
        ok = (pyaudio is not None)
        st = self.core.state if self.core else AudioState()
        detail = {
            "status": "OK" if ok else "WARNING",
            "module": "voice_input",
            "version": self.VERSION,
            "pyaudio": bool(pyaudio),
            "numpy": bool(np),
            "recording": bool(self.core and st.is_recording),
        }
        if self.core:
            with self.core._lock:
                detail["frames"] = st.frames_count
                detail["duration"] = self.core.duration()
                detail["last_error"] = st.error
        return detail

    # 事件入口（按你们约定）
    def handle_event(
        self,
        event_type: Literal[
            "voice.start_recording",
            "voice.stop_recording",
            "voice.pause",
            "voice.resume",
            "voice.save",
            "voice.status",
            "voice.record_until_silence",
        ],
        data: dict,
    ):
        mapping = {
            "voice.start_recording": self.action_voice_start,
            "voice.stop_recording": self.action_voice_stop,
            "voice.pause": self.action_voice_pause,
            "voice.resume": self.action_voice_resume,
            "voice.save": self.action_voice_save,
            "voice.status": self.action_voice_status,
            "voice.record_until_silence": self.action_voice_record_until_silence,
        }
        fn = mapping.get(event_type)
        if fn:
            return fn(context=self.context, params=data or {})
        return None

    # 动作注册
    def _register_actions(self) -> None:
        if self._actions_registered:
            return
        actions = [
            ("voice.start", self.action_voice_start, "开始录音"),
            ("voice.stop", self.action_voice_stop, "停止录音"),
            ("voice.pause", self.action_voice_pause, "暂停录音"),
            ("voice.resume", self.action_voice_resume, "恢复录音"),
            ("voice.save", self.action_voice_save, "保存WAV"),
            ("voice.status", self.action_voice_status, "查询状态"),
            ("voice.record_until_silence", self.action_voice_record_until_silence, "静音停止录音"),
        ]
        for name, handler, desc in actions:
            ACTION_DISPATCHER.register_action(
                name,
                # 兼容 dispatcher 的调用签名（c, params=None, **k）
                lambda c, params=None, _h=handler, **k: _h(c, params, **k),
                description=desc,
                module="voice_input",
            )
        self._actions_registered = True
        log.info(f"注册 {len(actions)} 个语音动作")

    # 动作实现
    def action_voice_start(self, context=None, params=None, **kwargs):
        if pyaudio is None:
            return {"status": "error", "msg": "PyAudio 未安装"}
        p = params or {}
        try:
            self.core.start(duration=p.get("duration"))
            cfg_show = {k: v for k, v in self.core.cfg.items() if k not in ("output_dir", "log_dir")}
            return {"status": "ok", "recording": True, "config": cfg_show}
        except Exception as e:
            return {"status": "error", "msg": str(e), "error_type": type(e).__name__}

    def action_voice_stop(self, context=None, params=None, **kwargs):
        if not self.core:
            return {"status": "error", "msg": "未初始化"}
        try:
            dur = self.core.stop()
            return {"status": "ok", "recording": False, "duration": dur, "frames": len(self.core.frames())}
        except Exception as e:
            return {"status": "error", "msg": str(e), "error_type": type(e).__name__}

    def action_voice_pause(self, context=None, params=None, **kwargs):
        if not self.core:
            return {"status": "error", "msg": "未初始化"}
        self.core.pause()
        return {"status": "ok", "paused": True}

    def action_voice_resume(self, context=None, params=None, **kwargs):
        if not self.core:
            return {"status": "error", "msg": "未初始化"}
        self.core.resume()
        return {"status": "ok", "paused": False}

    def action_voice_save(self, context=None, params=None, **kwargs):
        if not self.core:
            return {"status": "error", "msg": "未初始化"}
        name = (params or {}).get("filename", f"recording_{int(time.time())}.wav")
        try:
            path = self.core.save_wav(name)
            return {"status": "ok", "path": path, "size": os.path.getsize(path)}
        except Exception as e:
            return {"status": "error", "msg": str(e), "error_type": type(e).__name__}

    def action_voice_status(self, context=None, params=None, **kwargs):
        st = self.core.state if self.core else AudioState()
        return {
            "status": "ok",
            "recording": st.is_recording,
            "paused": st.is_paused,
            "duration": st.duration if not st.is_recording else (self.core.duration() if self.core else 0),
            "frames": st.frames_count,
            "last_audio": st.last_audio_time,
            "error": st.error,
            "version": self.VERSION,
        }

    def action_voice_record_until_silence(self, context=None, params=None, **kwargs):
        if pyaudio is None:
            return {"status": "error", "msg": "PyAudio 未安装"}
        p = params or {}
        try:
            dur = self.core.record_until_silence(
                silence_threshold=p.get("silence_threshold"),
                silence_duration=p.get("silence_duration"),
                max_duration=p.get("max_duration"),
            )
            return {"status": "ok", "duration": dur, "frames": len(self.core.frames())}
        except Exception as e:
            return {"status": "error", "msg": str(e), "error_type": type(e).__name__}

# 供 ModuleManager 反射
MODULE_CLASS = VoiceInputModule
