#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三花聚顶 · STT 语音识别模块（单文件稳定版：去 dataclass + 进程安全）
- Whisper 转写引擎（GPU/CPU 自动选择，支持降级）
- 多进程 + 资源监控
- 标准动作：stt.transcribe / stt.health
"""

import os
import sys
import time
import json
import gc
import signal
import queue
import shutil
import logging
import tempfile
import multiprocessing as mp
from pathlib import Path
from typing import Optional, Dict, Any, List

# ===== 框架基座（运行环境外可降级） =====
try:
    from core.core2_0.sanhuatongyu.module.base import BaseModule
    from core.core2_0.sanhuatongyu.logger import get_logger
    from core.core2_0.sanhuatongyu.action_dispatcher import dispatcher as ACTION_DISPATCHER
except Exception:
    class BaseModule:
        def __init__(self, meta=None, context=None): self.meta, self.context = meta, context
        def preload(self): ...
        def setup(self): ...
        def start(self): ...
        def stop(self): ...
        def cleanup(self): ...
        def health_check(self): ...
        def handle_event(self, event_type: str, data: dict): ...
    def get_logger(name):
        lg = logging.getLogger(name)
        if not lg.handlers:
            h = logging.StreamHandler()
            h.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"))
            lg.addHandler(h); lg.setLevel(logging.INFO)
        return lg
    class DummyDispatcher:
        def __init__(self): self._a={}
        def register_action(self, name, func, description="", permission="user", module=""): self._a[name]=dict(func=func,name=name)
        def unregister_action(self, name): self._a.pop(name, None)
        def list_actions(self, detailed=False): return [dict(name=k) for k in self._a] if detailed else list(self._a)
    ACTION_DISPATCHER = DummyDispatcher()

log = get_logger("stt_module")

# ===== 依赖探测（不崩） =====
try:
    import torch
except Exception:
    torch = None
try:
    import whisper  # openai-whisper
except Exception:
    whisper = None
try:
    import psutil
except Exception:
    psutil = None


# ===== 基础日志 =====
def setup_logger(log_file: Optional[Path] = None, log_level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("STTModule")
    level = getattr(logging, log_level.upper(), logging.INFO)
    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(process)d - %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    if not logger.handlers:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    if log_file:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(str(log_file), encoding="utf-8")
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        except Exception as e:
            logger.warning(f"日志文件不可用：{e}")
    return logger


# ===== 配置与任务（普通类实现，避免 dataclass 反射Bug） =====
class STTConfig:
    def __init__(self, **d):
        self.model_size = d.get("model_size", "base")       # [tiny, base, small, medium, large]
        self.device = d.get("device")                       # None / "cuda" / "cpu" / "cuda:0"
        self.language = d.get("language", "auto")
        self.compute_type = d.get("compute_type", "float16")  # "float32" / "float16"
        self.beam_size = int(d.get("beam_size", 5))
        self.temperature = float(d.get("temperature", 0.0))
        self.log_level = d.get("log_level", "INFO")
        self.log_file = d.get("log_file")
        self.max_concurrent = int(d.get("max_concurrent", 2))
        self.max_audio_duration = int(d.get("max_audio_duration", 300))
        self.max_audio_size = int(d.get("max_audio_size", 50 * 1024 * 1024))
        self.temp_dir = d.get("temp_dir", "/var/tmp/stt_processing")
        self.health_check_interval = int(d.get("health_check_interval", 60))
        self.auto_fallback = bool(d.get("auto_fallback", True))
        self.fallback_model = d.get("fallback_model", "base")
        self.gpu_threshold = float(d.get("gpu_threshold", 0.85))
        self.cpu_threshold = float(d.get("cpu_threshold", 0.80))
        self.disk_threshold = float(d.get("disk_threshold", 0.90))

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


class TranscriptionTask:
    def __init__(self, audio_file: str, task_id: str = "", callback_queue: Optional[Any] = None,
                 metadata: Optional[Dict[str, Any]] = None, timestamp: Optional[float] = None):
        self.audio_file = audio_file
        self.task_id = task_id or f"task_{int(time.time()*1000)}"
        self.callback_queue = callback_queue
        self.metadata = metadata or {}
        self.timestamp = timestamp or time.time()


# ===== 小工具 =====
def get_free_disk_space(path: str) -> int:
    try:
        base = path if os.path.exists(path) else "/"
        st = os.statvfs(base)
        return st.f_bavail * st.f_frsize
    except Exception:
        return 0

def get_gpu_utilization() -> float:
    if not (torch and hasattr(torch, "cuda") and torch.cuda.is_available()):
        return 0.0
    try:
        if shutil.which("nvidia-smi"):
            out = shutil.check_output(
                ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                stderr=subprocess.DEVNULL, text=True
            )
            vals = [int(x.strip()) for x in out.strip().splitlines() if x.strip().isdigit()]
            return (sum(vals) / len(vals) / 100.0) if vals else 0.0
    except Exception:
        pass
    return 0.0


# ===== 资源监控 =====
class ResourceMonitor:
    def __init__(self, config: STTConfig):
        self.config = config
        self.logger = logging.getLogger("STTModule.ResourceMonitor")
        self._last = 0.0

    def check(self) -> bool:
        now = time.time()
        if now - self._last < max(5, self.config.health_check_interval // 2):
            return True
        self._last = now

        cpu = psutil.cpu_percent(interval=0.1)/100.0 if psutil else 0.0
        disk = (psutil.disk_usage("/").percent/100.0) if psutil else 0.0
        gpu = get_gpu_utilization()
        if cpu > self.config.cpu_threshold or disk > self.config.disk_threshold or gpu > self.config.gpu_threshold:
            self.logger.warning(f"资源告警: CPU={cpu:.2f} DISK={disk:.2f} GPU={gpu:.2f}")
            return False
        return True


# ===== 引擎（主逻辑） =====
class STTEngine:
    def __init__(self, config: STTConfig, logger: logging.Logger):
        self.cfg = config
        self.log = logger
        self.model = None

    def _device(self) -> str:
        if self.cfg.device:
            return self.cfg.device
        if torch and hasattr(torch, "cuda") and torch.cuda.is_available():
            return "cuda"
        return "cpu"

    def load_model(self) -> bool:
        if whisper is None:
            self.log.error("未安装 openai-whisper，无法使用 STT")
            return False
        try:
            dev = self._device()
            self.log.info(f"加载 Whisper 模型：size={self.cfg.model_size} device={dev}")
            self.model = whisper.load_model(self.cfg.model_size, device=dev, download_root="/var/cache/whisper/models")
            return True
        except Exception as e:
            self.log.error(f"模型加载失败: {e}", exc_info=True)
            if self.cfg.auto_fallback and self.cfg.model_size != self.cfg.fallback_model:
                self.log.warning(f"尝试降级至 {self.cfg.fallback_model}")
                self.cfg.model_size = self.cfg.fallback_model
                return self.load_model()
            return False

    def _validate(self, path: str) -> Optional[str]:
        if not os.path.isfile(path):
            return "音频文件不存在"
        size = os.path.getsize(path)
        if size <= 0:
            return "空音频文件"
        if size > self.cfg.max_audio_size:
            return f"音频过大（>{self.cfg.max_audio_size/1024/1024:.0f}MB）"
        if get_free_disk_space(path) < 100 * 1024 * 1024:
            return "磁盘空间不足（<100MB）"
        return None

    def transcribe(self, task: TranscriptionTask) -> Dict[str, Any]:
        r = {"task_id": task.task_id, "audio_file": task.audio_file, "timestamp": time.time(),
             "model": self.cfg.model_size}
        err = self._validate(task.audio_file)
        if err:
            r.update({"status": "error", "error": err}); return r
        if self.model is None and not self.load_model():
            r.update({"status": "error", "error": "模型不可用"}); return r

        try:
            self.log.info(f"[转写] 开始: {task.audio_file}")
            st = time.time()
            result = self.model.transcribe(
                task.audio_file,
                language=None if self.cfg.language == "auto" else self.cfg.language,
                fp16=(self.cfg.compute_type == "float16"),
                temperature=self.cfg.temperature
            )
            text = (result.get("text") or "").strip()
            dur = time.time() - st
            self.log.info(f"[转写] 完成 用时{dur:.2f}s 字符{len(text)}")
            r.update({
                "status": "success",
                "text": text,
                "duration": dur,
                "language": result.get("language", ""),
                "confidence": result.get("avg_logprob", 0),
                "segments": [
                    {"start": s.get("start"), "end": s.get("end"), "text": (s.get("text") or '').strip()}
                    for s in (result.get("segments") or [])
                ]
            })
        except RuntimeError as re:
            if "CUDA out of memory" in str(re):
                self.log.error("GPU OOM，清理缓存")
                if torch and hasattr(torch, "cuda") and torch.cuda.is_available():
                    torch.cuda.empty_cache()
                gc.collect()
                r.update({"status": "retry", "error": "GPU OOM"})
            else:
                self.log.error(f"运行时错误: {re}", exc_info=True)
                r.update({"status": "error", "error": str(re)})
        except Exception as e:
            self.log.error(f"转写失败: {e}", exc_info=True)
            r.update({"status": "error", "error": str(e)})
        finally:
            try:
                if task.metadata.get("remove_after", True) and os.path.exists(task.audio_file):
                    os.remove(task.audio_file)
            except Exception:
                pass
        return r


# ===== 子进程入口（顶层定义，确保可 picklable） =====
def stt_worker(command_q: mp.Queue, result_q: mp.Queue, stop_ev: mp.Event, cfg_dict: Dict[str, Any]):
    cfg = STTConfig(**(cfg_dict or {}))
    logger = setup_logger(Path(cfg.log_file) if cfg.log_file else None, cfg.log_level)
    engine = STTEngine(cfg, logger)
    monitor = ResourceMonitor(cfg)

    def _on_signal(sig, frame):
        logger.info("收到终止信号，准备退出…"); stop_ev.set()
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    logger.info("STT 子进程已启动，等待任务…")
    active = 0
    while not stop_ev.is_set():
        try:
            if not monitor.check():
                time.sleep(0.8); continue
            task = command_q.get(timeout=0.5)
            if not isinstance(task, TranscriptionTask):
                logger.warning(f"忽略无效任务: {type(task)}"); continue
            active += 1
            res = engine.transcribe(task)
            (task.callback_queue or result_q).put(res)
            active -= 1
            if torch and hasattr(torch, "cuda") and torch.cuda.is_available() and active == 0:
                torch.cuda.empty_cache()
            gc.collect()
        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"进程循环异常: {e}", exc_info=True)
    logger.info("STT 子进程退出")


# ===== 模块实现 =====
class STTModule(BaseModule):
    VERSION = "1.0.1"

    def __init__(self, meta=None, context=None):
        super().__init__(meta, context)
        cfg = dict(getattr(meta, "config", {}) or {})
        self.config = STTConfig(**cfg)
        self.logger = setup_logger(Path(self.config.log_file) if self.config.log_file else None,
                                   self.config.log_level)

        self.command_q: Optional[mp.Queue] = None
        self.result_q: Optional[mp.Queue] = None
        self.stop_ev: Optional[mp.Event] = None
        self.proc: Optional[mp.Process] = None

        self._actions_registered = False
        self._started_at = 0.0
        self._last_health = {"status": "READY"}

    # 生命周期
    def preload(self):
        self._register_actions()
        bus = getattr(self.context, "event_bus", None)
        if bus:
            bus.subscribe("stt.transcribe", self._on_bus_event)
            bus.subscribe("stt.health", self._on_bus_event)
        log.info("[stt] preload 完成")

    def setup(self):
        Path(self.config.temp_dir).mkdir(parents=True, exist_ok=True)
        log.info("[stt] setup 完成")

    def start(self):
        if self.proc and self.proc.is_alive():
            return
        self.command_q = mp.Queue(maxsize=max(8, self.config.max_concurrent * 4))
        self.result_q = mp.Queue()
        self.stop_ev = mp.Event()
        self.proc = mp.Process(
            target=stt_worker,
            args=(self.command_q, self.result_q, self.stop_ev, self.config.to_dict()),
            name="STTProcess",
            daemon=True
        )
        self.proc.start()
        self._started_at = time.time()
        log.info("[stt] 模块启动，子进程已创建")

    def stop(self):
        if not self.proc:
            return
        log.info("[stt] 正在停止…")
        try:
            if self.stop_ev: self.stop_ev.set()
            self.proc.join(timeout=3)
            if self.proc.is_alive():
                self.proc.terminate()
        finally:
            self.proc = None
            self.command_q = None
            self.result_q = None
            self.stop_ev = None
        log.info("[stt] 已停止")

    def cleanup(self):
        self.stop()
        log.info("[stt] cleanup 完成")

    # 健康检查
    def health_check(self) -> Dict[str, Any]:
        running = bool(self.proc and self.proc.is_alive())
        status = "OK" if running else "ERROR"
        self._last_health = {
            "status": status,
            "module": "stt_module",
            "version": self.VERSION,
            "running": running,
            "started_at": self._started_at,
            "uptime": (time.time() - self._started_at) if running else 0,
            "backend": {
                "whisper_available": whisper is not None,
                "torch_available": torch is not None,
            }
        }
        return self._last_health

    # 事件（必实现，避免 abstract 报错）
    def handle_event(self, event_type: str, data: dict):
        if event_type in ("stt.transcribe", "stt.health", "stt_health"):
            if event_type == "stt.transcribe":
                return self.action_stt_transcribe(context=self.context, params=data or {})
            return self.action_stt_health(context=self.context, params=data or {})
        return None

    # 总线回调
    def _on_bus_event(self, event):
        try:
            name = getattr(event, "name", None) or (event.get("name") if isinstance(event, dict) else str(event))
            data = getattr(event, "data", None) or (event.get("data") if isinstance(event, dict) else {}) or {}
            return self.handle_event(name, data)
        except Exception as e:
            log.error(f"[stt] 总线事件异常: {e}")

    # 动作注册
    def _register_actions(self):
        if self._actions_registered:
            return
        ACTION_DISPATCHER.register_action(
            name="stt.transcribe",
            func=lambda context, params=None, **kw: self.action_stt_transcribe(context, params, **kw),
            description="提交音频文件进行转写",
            permission="user",
            module="stt_module"
        )
        ACTION_DISPATCHER.register_action(
            name="stt.health",
            func=lambda context, params=None, **kw: self.action_stt_health(context, params, **kw),
            description="查询 STT 模块健康状态",
            permission="user",
            module="stt_module"
        )
        self._actions_registered = True
        log.info("已注册动作：stt.transcribe / stt.health")

    # 动作实现
    def action_stt_health(self, context=None, params=None, **kwargs):
        return self.health_check()

    def action_stt_transcribe(self, context=None, params=None, **kwargs):
        p = params or {}
        src = p.get("audio_file")
        if not src:
            return {"status": "error", "error": "缺少 audio_file"}

        if not (self.proc and self.proc.is_alive()):
            self.start()
            if not (self.proc and self.proc.is_alive()):
                return {"status": "error", "error": "STT 子进程未启动"}

        # 拷贝到临时目录，避免权限/分区问题
        try:
            tmp_dir = Path(self.config.temp_dir)
            tmp_dir.mkdir(parents=True, exist_ok=True)
            dst = tmp_dir / f"stt_{int(time.time()*1000)}_{os.path.basename(src)}"
            shutil.copyfile(src, dst)
            audio_path = str(dst)
        except Exception as e:
            return {"status": "error", "error": f"无法准备音频文件: {e}"}

        task = TranscriptionTask(
            audio_file=audio_path,
            metadata={"remove_after": bool(p.get("remove_after", True))}
        )
        try:
            self.command_q.put_nowait(task)
        except Exception as e:
            return {"status": "error", "error": f"队列拥塞: {e}"}

        if not p.get("wait", False):
            return {"status": "queued", "task_id": task.task_id}

        # 阻塞等待
        timeout = float(p.get("timeout", 60))
        st = time.time()
        while time.time() - st < timeout:
            try:
                res = self.result_q.get(timeout=0.5)
                if res.get("task_id") == task.task_id:
                    return res
                else:
                    # 非本任务的结果，放回去
                    self.result_q.put(res)
            except queue.Empty:
                continue
        return {"status": "timeout", "task_id": task.task_id}


# 供模块管理器反射
MODULE_CLASS = STTModule

# 可选：元信息（若框架读取）
__metadata__ = {
    "id": "stt_module",
    "name": "三花聚顶 · STT 语音识别模块",
    "version": STTModule.VERSION,
    "entry_class": "modules.stt_module.module.STTModule",
    "events": ["stt.transcribe", "stt.health"],
    "dependencies": ["openai-whisper", "torch", "psutil"],
}

# -----------------------------
# Compatibility: export `entry`
# -----------------------------
def entry():
    """
    兼容模块加载器/子进程导入：提供稳定的 entry 符号。
    """
    for _name, _obj in globals().items():
        if isinstance(_obj, type) and _name.lower().endswith("module"):
            return _obj
    return None
