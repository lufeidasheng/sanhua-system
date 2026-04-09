# modules/audio_capture/module.py

"""
三花聚顶 · audio_capture 标准模块
作者: 三花聚顶开发团队
描述: 基于PyAudio的多进程音频采集模块，支持静音检测、设备热切换、事件通知与全局动作分发。
"""

import logging
import multiprocessing as mp
import time
import queue
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

import numpy as np
import pyaudio

from core.core2_0.sanhuatongyu.events import get_event_bus, is_event_bus_initialized
from core.core2_0.sanhuatongyu.module.base import BaseModule
from core.core2_0.sanhuatongyu.action_manager import ACTION_MANAGER

logger = logging.getLogger("audio_capture")
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(processName)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

@dataclass
class AudioCaptureConfig:
    rate: int = 16000
    chunk: int = 1024
    channels: int = 1
    format: int = pyaudio.paInt16
    device_index: Optional[int] = None
    queue_maxsize: int = 300
    buffer_seconds: float = 5.0
    silence_threshold: int = 200
    max_retry_count: int = 5
    retry_delay: float = 0.5
    enable_silence_detection: bool = True
    device_info: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "AudioCaptureConfig":
        return cls(**config_dict)

class AudioCapture(BaseModule):
    def __init__(self, meta, context):
        super().__init__(meta, context)
        self.config = AudioCaptureConfig.from_dict(
            context.config_manager.get("audio_capture", {})
        )
        self.event_bus = get_event_bus() if (get_event_bus and is_event_bus_initialized()) else None

        # 多进程通信
        self._audio_queue: Optional[mp.Queue] = None
        self._status_queue: Optional[mp.Queue] = None
        self._command_queue: Optional[mp.Queue] = None
        self._stop_event: Optional[mp.Event] = None
        self._process: Optional[mp.Process] = None

    def preload(self):
        logger.info(f"{self.meta.name} 预加载完成")

    def setup(self):
        logger.info(f"{self.meta.name} 模块设置完成")
        ACTION_MANAGER.register_action(
            name="audio_capture.start",
            func=self.start_capture,
            description="启动音频采集进程",
            permission="user",
            module=self.meta.name
        )
        ACTION_MANAGER.register_action(
            name="audio_capture.stop",
            func=self.stop_capture,
            description="停止音频采集进程",
            permission="user",
            module=self.meta.name
        )
        ACTION_MANAGER.register_action(
            name="audio_capture.list_devices",
            func=self.list_devices,
            description="获取可用音频输入设备",
            permission="user",
            module=self.meta.name
        )
        logger.info("audio_capture模块setup完成，动作已注册")

    def start(self):
        logger.info(f"{self.meta.name} 模块启动中")
        self._audio_queue = mp.Queue(maxsize=self.config.queue_maxsize)
        self._status_queue = mp.Queue(maxsize=100)
        self._command_queue = mp.Queue(maxsize=50)
        self._stop_event = mp.Event()

        self._process = mp.Process(
            target=self._audio_capture_process,
            args=(
                self._audio_queue,
                self._status_queue,
                self._command_queue,
                self._stop_event,
            ),
            daemon=True,
            name=f"{self.meta.name}_Process",
        )
        self._process.start()
        logger.info(f"{self.meta.name} 采集进程已启动")

    def stop(self):
        logger.info(f"{self.meta.name} 模块停止中")
        if self._stop_event:
            self._stop_event.set()
        if self._process and self._process.is_alive():
            self._process.join(timeout=5)
        logger.info(f"{self.meta.name} 模块已停止")

    def health_check(self) -> Dict[str, Any]:
        status = "WARNING"
        reason = "not_running"
        if getattr(self, "_process", None) is not None and self._process.is_alive():
            status = "OK"
            reason = "running"
        elif getattr(self, "degraded_reason", None):
            status = "DEGRADED"
            reason = str(getattr(self, "degraded_reason") or "").strip() or "degraded"

        return {
            "status": status,
            "module": getattr(self.meta, "name", "audio_capture"),
            "reason": reason,
            "process_alive": bool(getattr(self, "_process", None) and self._process.is_alive()),
        }

    def on_shutdown(self):
        logger.info(f"{self.meta.name} 模块关闭清理")
        self.stop()

    def handle_event(self, event_type: str, event_data: dict):
        pass

    def start_capture(self, context=None, params=None, **kwargs):
        logger.info("动作调用: start_capture")
        self.start()
        return {"status": "success", "message": "音频采集启动中"}

    def stop_capture(self, context=None, params=None, **kwargs):
        logger.info("动作调用: stop_capture")
        self.stop()
        return {"status": "success", "message": "音频采集停止中"}

    def list_devices(self, context=None, params=None, **kwargs):
        devices = []
        try:
            p = pyaudio.PyAudio()
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    devices.append({"index": i, "name": info["name"]})
            p.terminate()
            logger.info("动作调用: list_devices")
        except Exception as e:
            logger.error(f"获取设备列表失败: {e}")
        return {"status": "success", "devices": devices}

    def _audio_capture_process(self, audio_queue, status_queue, command_queue, stop_event):
        # ...（略，保留你的采集进程实现不变）...
        pass

MODULE_CLASS = AudioCapture
# === SANHUA_AUDIO_CAPTURE_MACOS_SPAWN_PATCH_START ===
try:
    import os as _sanhua_os
    import sys as _sanhua_sys

    def _sanhua_audio_log(level, msg):
        _logger = globals().get("logger") or globals().get("log")
        if _logger is not None:
            _fn = getattr(_logger, level, None)
            if callable(_fn):
                try:
                    _fn(msg)
                    return
                except Exception:
                    pass
        print(msg)

    if "AudioCapture" in globals():
        _SANHUA_ORIG_AUDIOCAPTURE_START = getattr(AudioCapture, "start", None)

        def _sanhua_audio_capture_start_safe(self, *args, **kwargs):
            # 手动总开关：GUI 测试时可关闭
            if _sanhua_os.environ.get("SANHUA_DISABLE_AUDIO_CAPTURE_PROCESS") == "1":
                self.started = False
                setattr(self, "degraded_reason", "disabled_by_env")
                _sanhua_audio_log(
                    "warning",
                    "audio_capture 已按环境变量禁用进程启动（SANHUA_DISABLE_AUDIO_CAPTURE_PROCESS=1）"
                )
                return False

            if _sanhua_sys.platform != "darwin":
                if callable(_SANHUA_ORIG_AUDIOCAPTURE_START):
                    return _SANHUA_ORIG_AUDIOCAPTURE_START(self, *args, **kwargs)
                return False

            try:
                if callable(_SANHUA_ORIG_AUDIOCAPTURE_START):
                    return _SANHUA_ORIG_AUDIOCAPTURE_START(self, *args, **kwargs)
                return False
            except TypeError as _e:
                _msg = str(_e)
                if "_thread._local" in _msg or "cannot pickle" in _msg:
                    self.started = False
                    setattr(self, "_process", None)
                    setattr(self, "degraded_reason", "spawn_pickle_thread_local")
                    _sanhua_audio_log(
                        "warning",
                        "audio_capture 在 macOS 下触发 spawn/pickle 问题，已自动降级跳过子进程启动"
                    )
                    return False
                raise
            except Exception as _e:
                # 只对 Darwin 启动阶段做软降级，避免 GUI 被拖死
                self.started = False
                setattr(self, "_process", None)
                setattr(self, "degraded_reason", f"darwin_start_degraded:{_e}")
                _sanhua_audio_log(
                    "warning",
                    f"audio_capture macOS 启动降级：{_e}"
                )
                return False

        AudioCapture.start = _sanhua_audio_capture_start_safe

except Exception as _sanhua_audio_capture_patch_error:
    print(f"⚠️ audio_capture macOS spawn patch init failed: {_sanhua_audio_capture_patch_error}")
# === SANHUA_AUDIO_CAPTURE_MACOS_SPAWN_PATCH_END ===
