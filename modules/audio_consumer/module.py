"""
三花聚顶 · audio_consumer 标准功能模块 (调试增强全量版)
作者: 三花聚顶开发团队
描述: 基于多进程架构的音频数据消费模块，支持流式音频存储、自动清理、队列监控、全局标准动作接口，并可被三花聚顶模块加载器自动识别。
"""

import os
import time
import logging
import multiprocessing as mp
import wave
import uuid
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

from core.core2_0.sanhuatongyu.module.base import BaseModule
from core.core2_0.sanhuatongyu.action_manager import ACTION_MANAGER
from core.core2_0.sanhuatongyu.logger import get_logger

logger = get_logger("audio_consumer")

# ==== 1. 配置结构 ====
@dataclass
class AudioConfig:
    rate: int = 16000
    chunk: int = 1024
    channels: int = 1
    save_path: str = "recordings"
    max_seconds_per_file: int = 3
    max_files: int = 100
    file_prefix: str = "audio"
    queue_warning_threshold: int = 80
    sample_width: int = 2  # 16-bit采样

    def __post_init__(self):
        assert self.rate > 0, "采样率必须为正整数"
        assert self.channels in (1, 2), "仅支持单声道或立体声"
        assert self.sample_width in (1, 2, 3, 4), "仅支持8/16/24/32位采样"

# ==== 2. 消费进程核心 ====
class AudioConsumerCore:
    def __init__(self, 
                 audio_queue: mp.Queue, 
                 stop_event: mp.Event,
                 result_queue: mp.Queue,  # 新增结果队列
                 config: AudioConfig):
        self.audio_queue = audio_queue
        self.stop_event = stop_event
        self.result_queue = result_queue
        self.config = config
        self.current_frames: List[bytes] = []
        self.file_counter = 0

        os.makedirs(self.config.save_path, exist_ok=True)
        logger.info(f"音频保存目录初始化完成")

    def _calculate_audio_duration(self, frames: List[bytes]) -> float:
        total_bytes = sum(len(frame) for frame in frames)
        bytes_per_second = self.config.rate * self.config.channels * self.config.sample_width
        return total_bytes / bytes_per_second

    def _save_to_file(self, frames: List[bytes]) -> Optional[str]:
        if not frames:
            logger.debug("收到空帧，跳过保存")
            return None
            
        duration = self._calculate_audio_duration(frames)
        filename = os.path.join(
            self.config.save_path,
            f"{self.config.file_prefix}_{uuid.uuid4().hex}.wav"  # 用UUID防冲突
        )
        try:
            with wave.open(filename, 'wb') as wf:
                wf.setnchannels(self.config.channels)
                wf.setsampwidth(self.config.sample_width)
                wf.setframerate(self.config.rate)
                wf.writeframes(b''.join(frames))
            logger.info(f"保存音频文件，时长{duration:.2f}s [{filename}]")
            self.result_queue.put(filename)  # 通过队列传回路径
            return filename
        except Exception as e:
            logger.error(f"保存失败: {str(e)[:200]}", exc_info=True)
            return None

    def _clean_old_files(self):
        try:
            files = []
            for f in os.listdir(self.config.save_path):
                if f.startswith(self.config.file_prefix) and f.endswith(".wav"):
                    try:
                        files.append((f, os.path.getctime(os.path.join(self.config.save_path, f))))
                    except (FileNotFoundError, PermissionError):
                        continue
            if len(files) > self.config.max_files:
                files.sort(key=lambda x: x[1])
                for f, _ in files[:len(files) - self.config.max_files]:
                    try:
                        os.remove(os.path.join(self.config.save_path, f))
                        logger.debug(f"清理旧文件: {f}")
                    except Exception as e:
                        logger.warning(f"清理失败: {str(e)[:200]}")
        except Exception as e:
            logger.error(f"清理异常: {str(e)[:200]}")

    def run(self):
        logger.info("音频消费者进程启动")
        while not self.stop_event.is_set():
            try:
                # 非阻塞获取+队列满处理
                if not self.audio_queue.empty():
                    data = self.audio_queue.get_nowait()
                    self.current_frames.append(data)
                    
                    # 时长检查
                    if self._calculate_audio_duration(self.current_frames) >= self.config.max_seconds_per_file:
                        self._save_to_file(self.current_frames)
                        self.current_frames = []
                        self._clean_old_files()
                else:
                    time.sleep(0.1)  # 减少空转CPU消耗
            except Exception as e:
                logger.warning(f"处理异常: {str(e)[:200]}")
                if self.current_frames:  # 异常时尝试保存剩余帧
                    self._save_to_file(self.current_frames)
                    self.current_frames = []

# ==== 3. 多进程管理器 ====
class AudioConsumerManager:
    def __init__(self, config: Optional[AudioConfig] = None):
        self.config = config or AudioConfig()
        self.audio_queue = mp.Queue(maxsize=100)
        self.stop_event = mp.Event()
        self.result_queue = mp.Queue()
        self.process: Optional[mp.Process] = None
        self._last_file_path: Optional[str] = None
        
        os.makedirs(self.config.save_path, exist_ok=True)

    @property
    def last_file_path(self) -> Optional[str]:
        try:
            while not self.result_queue.empty():
                self._last_file_path = self.result_queue.get_nowait()
        except:
            pass
        return self._last_file_path

    def start(self) -> Dict[str, Any]:
        if self.process and self.process.is_alive():
            return {"status": "error", "message": "进程已在运行"}
        self.stop_event.clear()
        self.process = mp.Process(
            target=self._consumer_process,
            args=(self.audio_queue, self.stop_event, self.result_queue, self.config),
            name="AudioConsumerProcess",
            daemon=True
        )
        self.process.start()
        return {"status": "success", "pid": self.process.pid}

    def stop(self) -> Dict[str, Any]:
        if not self.process or not self.process.is_alive():
            return {"status": "error", "message": "进程未运行"}
        self.stop_event.set()
        self.process.join(timeout=5)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join()
            logger.warning("进程强制终止")
        return {"status": "success", "last_file": self.last_file_path}

    @staticmethod
    def _consumer_process(audio_queue, stop_event, result_queue, config):
        try:
            AudioConsumerCore(audio_queue, stop_event, result_queue, config).run()
        except Exception as e:
            logger.critical(f"消费者进程崩溃: {str(e)}", exc_info=True)

# ==== 4. 标准模块类 ====
class AudioConsumerModule(BaseModule):
    """
    三花聚顶 · 音频消费者标准模块
    """
    def preload(self):
        logger.info("audio_consumer 模块预加载完成")

    def setup(self):
        if not hasattr(self.context, "audio_consumer_manager"):
            self.context.audio_consumer_manager = AudioConsumerManager()
        ACTION_MANAGER.register_action(
            name="audio_consumer.start",
            func=self.start_recording,
            description="启动音频录制",
            permission="user",
            module=self.meta.name
        )
        ACTION_MANAGER.register_action(
            name="audio_consumer.stop",
            func=self.stop_recording,
            description="停止音频录制",
            permission="user",
            module=self.meta.name
        )
        ACTION_MANAGER.register_action(
            name="audio_consumer.get_last_file",
            func=self.get_last_file,
            description="获取最后录音文件",
            permission="user",
            module=self.meta.name
        )
        logger.info("audio_consumer 模块setup完成，动作注册完毕")

    def start(self):
        logger.info("audio_consumer 模块启动")

    def stop(self):
        logger.info("audio_consumer 模块停止")
        self.context.audio_consumer_manager.stop()

    def health_check(self) -> Dict[str, Any]:
        mgr = getattr(self.context, "audio_consumer_manager", None)
        proc = getattr(mgr, "process", None) if mgr else None
        running = bool(proc and proc.is_alive())
        status = "OK" if running else "STOPPED"
        reason = None if running else "not_running"
        return {
            "status": status,
            "reason": reason,
            "module": getattr(self.meta, "name", "audio_consumer"),
            "running": running,
            "pid": getattr(proc, "pid", None) if running else None,
        }

    def handle_event(self, event_type: str, event_data: dict):
        pass

    def start_recording(self, context=None, params=None, **kwargs):
        return self.context.audio_consumer_manager.start()

    def stop_recording(self, context=None, params=None, **kwargs):
        return self.context.audio_consumer_manager.stop()

    def get_last_file(self, context=None, params=None, **kwargs):
        return self.context.audio_consumer_manager.last_file_path or "无录音文件"

# ==== 5. 反射导出主类 ====
MODULE_CLASS = AudioConsumerModule
