# -*- coding: utf-8 -*-
"""
三花聚顶 · voice_ai_core（企业版 · 自适应设备/采样率 · 去占位）
- 专业音频采集（PyAudio，设备/采样率自适应）
- 唤醒词检测（带通滤波 + 能量/幅度/谱心 + 冷却/连发）
- 唤醒后抓取上下文音频，调用 Whisper 本地模型转写
- manifest+BaseModule 规范实现 + handle_event
"""

import os
import time
import json
import hashlib
import threading
import multiprocessing as mp
from queue import Empty
from typing import Optional, Dict, Any, List, Tuple

# ==== 平台基座 ====
from core.core2_0.sanhuatongyu.module.base import BaseModule
from core.core2_0.sanhuatongyu.logger import get_logger
from core.core2_0.sanhuatongyu.action_dispatcher import dispatcher as ACTION_DISPATCHER

log = get_logger("voice_ai_core")

# ==== 依赖（软失败）====
try:
    import pyaudio
except Exception as e:
    pyaudio = None
    log.warning(f"PyAudio 不可用：{e}")

try:
    import numpy as np
except Exception as e:
    np = None
    log.warning(f"NumPy 不可用：{e}")

try:
    from scipy.signal import butter, lfilter
except Exception as e:
    butter = lfilter = None
    log.warning(f"SciPy 不可用（降级滤波能力）：{e}")

def _lazy_import_whisper():
    try:
        import whisper
        return whisper
    except Exception as e:
        log.warning(f"whisper 导入失败：{e}")
        return None

# ================== 路径与配置 ==================
def _expand_user(p: str) -> str:
    return os.path.abspath(os.path.expanduser(p))

def _xdg_data_dir() -> str:
    return os.environ.get("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share"))

def _xdg_cache_dir() -> str:
    return os.environ.get("XDG_CACHE_HOME", os.path.join(os.path.expanduser("~"), ".cache"))

DEFAULT_CFG: Dict[str, Any] = {
    "models_dir": os.path.join(_xdg_data_dir(), "voice_ai_core", "models"),
    "work_dir": os.path.join(_xdg_cache_dir(), "voice_ai_core"),
    "model_name": "base",
    "whisper_device": "auto",        # auto/cpu/cuda
    "audio": {
        "rate": 16000,               # 首选；会自动回退
        "fallback_rates": [48000, 44100, 32000, 22050, 16000],
        "channels": 1,
        "chunk": 1024,
        "format": "paInt16",         # PyAudio 常量名
        "silence_threshold": 800,
        "buffer_seconds": 1.5,
        "device_index": None,        # 可指定; None=自动
        "device_name": ""            # 支持按名称匹配
    },
    "wakeword": {
        "amp_threshold": 1200,
        "energy_threshold": 0.45,
        "consecutive_frames": 5,
        "cooldown": 1.5,             # 秒
        "post_record_seconds": 3.0
    },
    "heartbeat": {
        "interval": 5.0,
        "timeout": 15.0
    }
}

# 官方 hash→url 表（可补充）
_WHISPER_MODEL_INDEX = {
    "base": (
        "ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e",
        "https://openaipublic.azureedge.net/main/whisper/models/ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e/base.pt"
    ),
}

def _pya_format(name: str):
    if not pyaudio:
        return None
    return getattr(pyaudio, name, None)

def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

# ================== 设备工具 ==================
def _list_input_devices(pa: "pyaudio.PyAudio") -> List[Dict[str, Any]]:
    out = []
    try:
        n = pa.get_device_count()
        for i in range(n):
            info = pa.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0:
                out.append({
                    "index": i,
                    "name": info.get("name"),
                    "defaultSampleRate": int(info.get("defaultSampleRate", 0) or 0),
                    "maxInputChannels": int(info.get("maxInputChannels", 0))
                })
    except Exception as e:
        log.warning(f"列举输入设备失败：{e}")
    return out

def _match_device_index(pa: "pyaudio.PyAudio", want_index: Optional[int], want_name: str) -> Optional[int]:
    devices = _list_input_devices(pa)
    if want_index is not None:
        if any(d["index"] == want_index for d in devices):
            return want_index
    if want_name:
        want = want_name.lower()
        for d in devices:
            if want in (d["name"] or "").lower():
                return d["index"]
    # 返回第一个可用
    return devices[0]["index"] if devices else None

# ================== 专业音频采集 ==================
class ProfessionalAudioCapture:
    def __init__(self, cfg: Dict[str, Any], ring_buffer: "RingBuffer"):
        self.cfg = cfg
        self.p = None
        self.stream = None
        self.input_index = None
        self.last_heartbeat = time.monotonic()
        self._run = False
        self._ring = ring_buffer
        self._active_rate = None  # 实际成功的采样率
        self._fmt = _pya_format(self.cfg["audio"]["format"]) if pyaudio else None

    def _open_with_params(self, rate: int, index: Optional[int]) -> bool:
        """尝试特定 (rate, index) 打开流"""
        try:
            self.stream = self.p.open(
                format=self._fmt,
                channels=self.cfg["audio"]["channels"],
                rate=rate,
                input=True,
                input_device_index=index,
                frames_per_buffer=self.cfg["audio"]["chunk"]
            )
            self._active_rate = rate
            log.info(f"采集已打开 rate={rate} chunk={self.cfg['audio']['chunk']} device_index={index}")
            return True
        except Exception as e:
            log.warning(f"打开音频流失败（rate={rate}, device={index}）：{e}")
            self.stream = None
            return False

    def open(self) -> bool:
        if pyaudio is None:
            log.error("PyAudio 不可用，无法采集")
            return False
        try:
            self.p = pyaudio.PyAudio()
            # 选择设备
            want_index = self.cfg["audio"].get("device_index", None)
            want_name = (self.cfg["audio"].get("device_name") or "").strip()
            self.input_index = _match_device_index(self.p, want_index, want_name)
            if self.input_index is None:
                log.error("没有可用的输入设备")
                return False

            # 采样率优先级：用户的 rate → fallback 列表（去重）
            pri = [int(self.cfg["audio"]["rate"])]
            fall = [r for r in self.cfg["audio"].get("fallback_rates", []) if r not in pri]
            try_list = pri + fall

            # 尝试逐个 rate 打开
            for r in try_list:
                if self._open_with_params(r, self.input_index):
                    return True

            log.error(f"所有候选采样率均失败：{try_list}")
            return False
        except Exception as e:
            log.error(f"初始化采集失败：{e}")
            return False

    def capture_loop(self, audio_q: mp.Queue, stop_evt: mp.Event, hb_q: Optional[mp.Queue] = None):
        if not self.stream and not self.open():
            return
        self._run = True
        silent_frames = 0
        max_silent = 5
        hb_interval = self.cfg["heartbeat"]["interval"]

        try:
            while not stop_evt.is_set() and self._run:
                now = time.monotonic()
                if hb_q and now - self.last_heartbeat >= hb_interval:
                    hb_q.put_nowait({
                        "type": "heartbeat",
                        "process": "AudioCapture",
                        "ts": time.time(),
                        "rate": self._active_rate,
                        "device_index": self.input_index
                    })
                    self.last_heartbeat = now

                data = self.stream.read(self.cfg["audio"]["chunk"], exception_on_overflow=False)
                if not data:
                    time.sleep(0.01)
                    continue

                # 推入环形缓存给“唤醒前背景”使用
                self._ring.push(data)

                if np is not None:
                    arr = np.frombuffer(data, dtype=np.int16)
                    if arr.size and np.max(np.abs(arr)) < self.cfg["audio"]["silence_threshold"]:
                        silent_frames += 1
                        if silent_frames > max_silent:
                            continue
                    else:
                        silent_frames = 0

                try:
                    audio_q.put_nowait(data)
                except Exception:
                    try:
                        audio_q.get_nowait()
                    except Empty:
                        pass
                    audio_q.put_nowait(data)
        except Exception as e:
            log.error(f"采集循环异常：{e}")
        finally:
            self.close()

    def close(self):
        self._run = False
        try:
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
        except Exception:
            pass
        try:
            if self.p:
                self.p.terminate()
        except Exception:
            pass
        log.info("采集已关闭")

# ================== 环形缓存（保存唤醒前背景） ==================
class RingBuffer:
    def __init__(self, capacity_bytes: int):
        self._cap = capacity_bytes
        self._buf = bytearray(capacity_bytes)
        self._w = 0
        self._len = 0
        self._lock = threading.Lock()

    def push(self, data: bytes):
        with self._lock:
            n = len(data)
            if n >= self._cap:
                self._buf[:] = data[-self._cap:]
                self._w = 0
                self._len = self._cap
                return
            end = self._w + n
            if end <= self._cap:
                self._buf[self._w:end] = data
            else:
                first = self._cap - self._w
                self._buf[self._w:] = data[:first]
                self._buf[:n - first] = data[first:]
            self._w = (self._w + n) % self._cap
            self._len = min(self._len + n, self._cap)

    def snapshot(self) -> bytes:
        with self._lock:
            if self._len == 0:
                return b""
            start = (self._w - self._len) % self._cap
            if start + self._len <= self._cap:
                return bytes(self._buf[start:start + self._len])
            else:
                first = self._cap - start
                return bytes(self._buf[start:] + self._buf[:self._len - first])

# ================== 唤醒词检测 ==================
class WakeWordDetector:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.last_heartbeat = time.monotonic()
        self.detection_count = 0
        self.last_detection_ts = 0.0
        self._bp = None
        if butter and lfilter and np is not None:
            nyq = 0.5 * self.cfg["audio"]["rate"]
            low = 300 / nyq
            high = 4000 / nyq
            self._bp = butter(4, [low, high], btype="band")

    def _apply_filter(self, chunk: bytes) -> bytes:
        if not self._bp or np is None:
            return chunk
        b, a = self._bp
        arr = np.frombuffer(chunk, dtype=np.int16)
        if arr.size == 0:
            return chunk
        fil = lfilter(b, a, arr).astype(np.int16)
        return fil.tobytes()

    def _features(self, arr: "np.ndarray") -> Dict[str, float]:
        amp = float(np.max(np.abs(arr))) if arr.size else 0.0
        energy = float(np.sqrt(np.mean(arr.astype(np.float32)**2))) if arr.size else 0.0
        if arr.size:
            mags = np.abs(arr.astype(np.float32))
            idx = np.arange(arr.size, dtype=np.float32)
            centroid = float(np.sum(idx * mags) / (np.sum(mags) + 1e-6))
        else:
            centroid = 0.0
        return {"amp": amp, "energy": energy, "centroid": centroid}

    def loop(self, audio_q: mp.Queue, event_q: mp.Queue, stop_evt: mp.Event, hb_q: Optional[mp.Queue] = None):
        hb_interval = self.cfg["heartbeat"]["interval"]
        cooldown = self.cfg["wakeword"]["cooldown"]
        need_frames = self.cfg["wakeword"]["consecutive_frames"]
        amp_thr = self.cfg["wakeword"]["amp_threshold"]
        ene_thr = self.cfg["wakeword"]["energy_threshold"]

        try:
            while not stop_evt.is_set():
                now = time.monotonic()
                if hb_q and now - self.last_heartbeat >= hb_interval:
                    hb_q.put_nowait({"type": "heartbeat", "process": "WakeWordDetector", "ts": time.time()})
                    self.last_heartbeat = now

                try:
                    chunk = audio_q.get(timeout=0.2)
                except Empty:
                    continue

                chunk = self._apply_filter(chunk)
                if np is None:
                    passed = len(chunk) > 0
                else:
                    arr = np.frombuffer(chunk, dtype=np.int16)
                    if arr.size == 0:
                        continue
                    f = self._features(arr)
                    if f["amp"] > amp_thr and f["energy"] > ene_thr and f["centroid"] > 500:
                        if now - self.last_detection_ts < cooldown:
                            passed = False
                        else:
                            self.detection_count += 1
                            passed = self.detection_count >= need_frames
                    else:
                        self.detection_count = max(0, self.detection_count - 1)
                        passed = False

                if passed:
                    self.detection_count = 0
                    self.last_detection_ts = now
                    event_q.put_nowait({"type": "wake", "ts": time.time()})
        except Exception as e:
            log.error(f"唤醒词循环异常：{e}")

# ================== Whisper 管理 ==================
class WhisperManager:
    def __init__(self, models_dir: str, model_name: str, device_pref: str = "auto"):
        self.models_dir = _expand_user(models_dir)
        self.model_name = model_name
        self.device_pref = device_pref
        self.model = None
        os.makedirs(self.models_dir, exist_ok=True)

    @property
    def model_path(self) -> str:
        return os.path.join(self.models_dir, f"{self.model_name}.pt")

    def ensure_model(self) -> bool:
        if os.path.exists(self.model_path):
            return True
        return self.download_model()

    def download_model(self) -> bool:
        from urllib.request import urlopen
        import shutil
        index = _WHISPER_MODEL_INDEX.get(self.model_name)
        if not index:
            log.error(f"未知模型：{self.model_name}")
            return False
        expected_sha256, url = index
        tmp_path = self.model_path + ".downloading"
        try:
            log.info(f"开始下载 {self.model_name}：{url}")
            with urlopen(url) as r, open(tmp_path, "wb") as f:
                shutil.copyfileobj(r, f)
            sha = _sha256_file(tmp_path)
            if expected_sha256 and sha != expected_sha256:
                log.error(f"模型校验失败：期望={expected_sha256[:16]} 实际={sha[:16]}")
                os.remove(tmp_path)
                return False
            os.replace(tmp_path, self.model_path)
            log.info(f"下载完成：{self.model_path}")
            return True
        except Exception as e:
            log.error(f"下载失败：{e}")
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            return False

    def _pick_device(self) -> str:
        if self.device_pref in ("cpu", "cuda"):
            return self.device_pref
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    def load(self):
        whisper = _lazy_import_whisper()
        if whisper is None:
            return None
        device = self._pick_device()
        try:
            if os.path.exists(self.model_path):
                log.info(f"本地加载 Whisper：{self.model_path} device={device}")
                self.model = whisper.load_model(self.model_path, device=device)
            else:
                log.info(f"按名称加载 Whisper：{self.model_name} device={device}")
                self.model = whisper.load_model(self.model_name, device=device)
            return self.model
        except Exception as e:
            log.error(f"加载 Whisper 失败：{e}")
            return None

    def transcribe(self, wav_path: str) -> str:
        if self.model is None:
            if self.load() is None:
                return ""
        try:
            result = self.model.transcribe(wav_path, language="zh")
            return (result.get("text") or "").strip()
        except Exception as e:
            log.error(f"转写失败：{e}")
            return ""

# ================== WAV 工具 ==================
def _write_wav(path: str, data: bytes, rate: int, channels: int, sampwidth_bytes: int = 2):
    import wave
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth_bytes)
        wf.setframerate(rate)
        wf.writeframes(data)

def _pcm_bytes_per_chunk(rate: int, chunk: int, channels: int, sampwidth_bytes: int = 2) -> int:
    return chunk * channels * sampwidth_bytes

# ================== 进程编排函数 ==================
def _proc_audio_capture(cfg: Dict[str, Any], audio_q: mp.Queue, stop_evt: mp.Event, hb_q: mp.Queue, ring_conf: Tuple[int]):
    ring = RingBuffer(ring_conf[0])
    cap = ProfessionalAudioCapture(cfg, ring)
    cap.capture_loop(audio_q, stop_evt, hb_q)

def _proc_wakeword(cfg: Dict[str, Any], audio_q: mp.Queue, event_q: mp.Queue, stop_evt: mp.Event, hb_q: mp.Queue):
    det = WakeWordDetector(cfg)
    det.loop(audio_q, event_q, stop_evt, hb_q)

# ================== 模块实现 ==================
class VoiceAICoreModule(BaseModule):
    VERSION = "1.2.0"

    def __init__(self, meta=None, context=None):
        super().__init__(meta, context)
        self.cfg: Dict[str, Any] = {}
        self.models_dir: str = ""
        self.work_dir: str = ""
        self.whisper_mgr: Optional[WhisperManager] = None

        # 运行期
        self._audio_q: Optional[mp.Queue] = None
        self._event_q: Optional[mp.Queue] = None
        self._hb_q: Optional[mp.Queue] = None
        self._stop_evt: Optional[mp.Event] = None
        self._proc_cap: Optional[mp.Process] = None
        self._proc_det: Optional[mp.Process] = None

        self._started = False
        self._init_ts = time.time()
        self._ring_bytes = 0
        self._sampwidth = 2  # 16bit

        # 主进程 ring（用于写 WAV）
        self._ring = None  # type: Optional[RingBuffer]
        # 最近一次成功的采样率（由心跳回传）
        self._active_rate = None
        # 设备列表缓存
        self._device_cache: List[Dict[str, Any]] = []

    # ---- 生命周期 ----
    def preload(self):
        self._register_actions()

    def setup(self):
        user_cfg = getattr(self.meta, "config", {}) if self.meta else {}
        self.cfg = _deep_merge(DEFAULT_CFG, user_cfg)
        self.models_dir = _expand_user(self.cfg["models_dir"])
        self.work_dir = _expand_user(self.cfg["work_dir"])
        os.makedirs(self.models_dir, exist_ok=True)
        os.makedirs(self.work_dir, exist_ok=True)

        bytes_per_chunk = _pcm_bytes_per_chunk(
            self.cfg["audio"]["rate"], self.cfg["audio"]["chunk"], self.cfg["audio"]["channels"], self._sampwidth
        )
        chunks_in_buffer = int(self.cfg["audio"]["buffer_seconds"] * self.cfg["audio"]["rate"] / self.cfg["audio"]["chunk"])
        self._ring_bytes = max(bytes_per_chunk * max(1, chunks_in_buffer), bytes_per_chunk * 5)
        self._ring = RingBuffer(self._ring_bytes)

        self.whisper_mgr = WhisperManager(self.models_dir, self.cfg["model_name"], self.cfg.get("whisper_device", "auto"))
        log.info(f"voice_ai_core setup 完成 models_dir={self.models_dir} work_dir={self.work_dir} model={self.cfg['model_name']}")

    def start(self):
        if self._started:
            return
        self._audio_q = mp.Queue(maxsize=100)
        self._event_q = mp.Queue(maxsize=10)
        self._hb_q = mp.Queue(maxsize=50)
        self._stop_evt = mp.Event()

        self._proc_cap = mp.Process(
            target=_proc_audio_capture,
            args=(self.cfg, self._audio_q, self._stop_evt, self._hb_q, (self._ring_bytes,)),
            name="AudioCaptureProcess",
            daemon=True
        )
        self._proc_det = mp.Process(
            target=_proc_wakeword,
            args=(self.cfg, self._audio_q, self._event_q, self._stop_evt, self._hb_q),
            name="WakeWordProcess",
            daemon=True
        )
        self._proc_cap.start()
        self._proc_det.start()
        self._started = True
        log.info(f"voice_ai_core 已启动 uptime={time.time() - self._init_ts:.2f}s")

        threading.Thread(target=self._audio_mirror, name="VoiceAI_AudioMirror", daemon=True).start()
        threading.Thread(target=self._event_loop, name="VoiceAI_EventLoop", daemon=True).start()
        threading.Thread(target=self._hb_loop, name="VoiceAI_Heartbeat", daemon=True).start()

    def post_start(self):
        # 预热模型（不阻塞启动）
        def _warm():
            try:
                if self.whisper_mgr and self.whisper_mgr.ensure_model():
                    self.whisper_mgr.load()
            except Exception as e:
                log.warning(f"Whisper 预热失败：{e}")
        threading.Thread(target=_warm, name="VoiceAI_Warmup", daemon=True).start()

    def stop(self):
        if not self._started:
            return
        try:
            if self._stop_evt:
                self._stop_evt.set()
            for p in (self._proc_cap, self._proc_det):
                if p and p.is_alive():
                    p.join(timeout=3.0)
                    if p.is_alive():
                        p.terminate()
        finally:
            self._proc_cap = self._proc_det = None
            self._audio_q = self._event_q = self._hb_q = None
            self._stop_evt = None
            self._started = False
            log.info("voice_ai_core 已停止")

    def cleanup(self):
        self.stop()

    # ---- 事件/后台线程 ----
    def _audio_mirror(self):
        """镜像采集队列到主进程 ring，用于保存唤醒前背景"""
        while self._started and self._audio_q:
            try:
                data = self._audio_q.get(timeout=0.5)
                if self._ring:
                    self._ring.push(data)
            except Empty:
                pass
            except Exception as e:
                log.error(f"音频镜像异常：{e}")

    def _event_loop(self):
        """收到唤醒事件 -> 抓取前/后音频保存 WAV -> Whisper 识别"""
        while self._started and self._event_q:
            try:
                evt = self._event_q.get(timeout=0.5)
                if evt.get("type") == "wake":
                    log.info("检测到唤醒事件，准备抓取前后音频")
                    wav_path = self._dump_surrounding_audio()
                    if wav_path and self.whisper_mgr:
                        text = self.whisper_mgr.transcribe(wav_path)
                        if text:
                            log.info(f"识别结果：{text}")
                            if hasattr(self.context, "event_bus") and self.context.event_bus:
                                try:
                                    self.context.event_bus.publish("voice_ai.transcribed", {"text": text, "wav": wav_path})
                                except Exception:
                                    pass
            except Empty:
                pass
            except Exception as e:
                log.error(f"事件循环异常：{e}")

    def _hb_loop(self):
        """处理子进程心跳（更新采样率/设备信息）"""
        while self._started and self._hb_q:
            try:
                msg = self._hb_q.get(timeout=1.0)
                if msg.get("type") == "heartbeat" and msg.get("process") == "AudioCapture":
                    self._active_rate = msg.get("rate")
            except Empty:
                pass
            except Exception as e:
                log.error(f"心跳处理异常：{e}")

    def _dump_surrounding_audio(self) -> Optional[str]:
        """把 ring 里的前背景 + post_record_seconds 的后录拼到一个 wav"""
        try:
            pre = self._ring.snapshot() if self._ring else b""
            post_secs = float(self.cfg["wakeword"]["post_record_seconds"])
            # 用实际采样率（如果拿到了），否则用配置率
            rate = int(self._active_rate or self.cfg["audio"]["rate"])
            chunk = self.cfg["audio"]["chunk"]
            channels = self.cfg["audio"]["channels"]
            need_chunks = max(1, int(post_secs * rate / chunk))

            post = bytearray()
            got = 0
            start = time.time()
            while got < need_chunks and (time.time() - start) < (post_secs + 1.0):
                try:
                    data = self._audio_q.get(timeout=0.2)
                    post.extend(data)
                    got += 1
                except Empty:
                    pass

            data_all = bytes(pre[-self._ring_bytes:]) + bytes(post)
            ts = time.strftime("%Y%m%d_%H%M%S")
            out_dir = os.path.join(self.work_dir, "recordings")
            out_path = os.path.join(out_dir, f"wake_{ts}.wav")
            _write_wav(out_path, data_all, rate, channels, self._sampwidth)
            log.info(f"已保存唤醒片段到：{out_path}")
            return out_path
        except Exception as e:
            log.error(f"保存唤醒片段失败：{e}")
            return None

    # ---- 健康 ----
    def health_check(self) -> Dict[str, Any]:
        deps = {
            "pyaudio": bool(pyaudio),
            "numpy": bool(np),
            "scipy": bool(butter and lfilter),
            "whisper": bool(_lazy_import_whisper()),
        }
        status = {
            "status": "OK" if self._started else "IDLE",
            "module": "voice_ai_core",
            "version": self.VERSION,
            "running": self._started,
            "model_ready": bool(self.whisper_mgr and os.path.exists(self.whisper_mgr.model_path)),
            "models_dir": self.models_dir,
            "work_dir": self.work_dir,
            "active_sample_rate": self._active_rate,
            "deps": deps
        }
        return status

    # ---- 事件入口（供 event_bus 使用）----
    def handle_event(self, event_name: str, data: Optional[Dict[str, Any]] = None):
        if event_name == "voice_ai.start":
            return self.action_start()
        if event_name == "voice_ai.stop":
            return self.action_stop()
        if event_name == "voice_ai.download_model":
            return self.action_download_model(params=data or {})
        if event_name == "voice_ai.transcribe":
            return self.action_transcribe(params=data or {})
        if event_name == "voice_ai.set_device":
            return self.action_set_device(params=data or {})
        if event_name == "voice_ai.devices":
            return self.action_list_devices()
        return None

    # ---- 动作注册 ----
    def _register_actions(self):
        ACTION_DISPATCHER.register_action(
            "voice_ai.start",
            lambda c, params=None, **k: self.action_start(c, params or {}, **k),
            description="启动语音AI核心（采集+唤醒词）",
            module="voice_ai_core"
        )
        ACTION_DISPATCHER.register_action(
            "voice_ai.stop",
            lambda c, params=None, **k: self.action_stop(c, params or {}, **k),
            description="停止语音AI核心",
            module="voice_ai_core"
        )
        ACTION_DISPATCHER.register_action(
            "voice_ai.status",
            lambda c, params=None, **k: self.action_status(c, params or {}, **k),
            description="查看语音AI核心状态",
            module="voice_ai_core"
        )
        ACTION_DISPATCHER.register_action(
            "voice_ai.download_model",
            lambda c, params=None, **k: self.action_download_model(c, params or {}, **k),
            description="下载 Whisper 模型（本地保存）",
            module="voice_ai_core"
        )
        ACTION_DISPATCHER.register_action(
            "voice_ai.transcribe",
            lambda c, params=None, **k: self.action_transcribe(c, params or {}, **k),
            description="离线转写指定 WAV 文件",
            module="voice_ai_core"
        )
        ACTION_DISPATCHER.register_action(
            "voice_ai.set_config",
            lambda c, params=None, **k: self.action_set_config(c, params or {}, **k),
            description="动态设置模块配置（部分生效需重启模块）",
            module="voice_ai_core"
        )
        ACTION_DISPATCHER.register_action(
            "voice_ai.get_config",
            lambda c, params=None, **k: self.action_get_config(c, params or {}, **k),
            description="获取当前配置",
            module="voice_ai_core"
        )
        ACTION_DISPATCHER.register_action(
            "voice_ai.devices",
            lambda c, params=None, **k: self.action_list_devices(c, params or {}, **k),
            description="列出可用音频输入设备",
            module="voice_ai_core"
        )
        ACTION_DISPATCHER.register_action(
            "voice_ai.set_device",
            lambda c, params=None, **k: self.action_set_device(c, params or {}, **k),
            description="切换音频输入设备（支持索引或名称）",
            module="voice_ai_core"
        )
        log.info("voice_ai_core 动作注册完成")

    # ---- 动作实现 ----
    def action_start(self, context=None, params=None, **kwargs):
        try:
            if not self._started:
                self.start()
            return {"status": "ok", "running": True}
        except Exception as e:
            return {"status": "error", "msg": str(e)}

    def action_stop(self, context=None, params=None, **kwargs):
        try:
            self.stop()
            return {"status": "ok", "running": False}
        except Exception as e:
            return {"status": "error", "msg": str(e)}

    def action_status(self, context=None, params=None, **kwargs):
        return self.health_check()

    def action_download_model(self, context=None, params=None, **kwargs):
        name = (params or {}).get("model") or self.cfg["model_name"]
        mgr = WhisperManager(self.models_dir, name, self.cfg.get("whisper_device", "auto"))
        ok = mgr.ensure_model()
        if ok and self.whisper_mgr and name == self.cfg["model_name"]:
            # 如果是当前模型，置换路径已就绪
            pass
        return {"status": "ok" if ok else "error", "model": name, "path": mgr.model_path if ok else ""}

    def action_transcribe(self, context=None, params=None, **kwargs):
        wav = (params or {}).get("path")
        if not wav or not os.path.exists(wav):
            return {"status": "error", "msg": "缺少有效的 WAV 路径"}
        text = self.whisper_mgr.transcribe(wav) if self.whisper_mgr else ""
        return {"status": "ok", "text": text}

    def action_set_config(self, context=None, params=None, **kwargs):
        try:
            if not isinstance(params, dict):
                return {"status": "error", "msg": "参数必须是对象"}
            allow_keys = ["model_name", "whisper_device", "wakeword", "audio"]
            for k in allow_keys:
                if k in params:
                    if isinstance(params[k], dict) and isinstance(self.cfg.get(k), dict):
                        self.cfg[k] = _deep_merge(self.cfg[k], params[k])
                    else:
                        self.cfg[k] = params[k]
            if "model_name" in params and self.whisper_mgr:
                self.whisper_mgr = WhisperManager(self.models_dir, self.cfg["model_name"], self.cfg.get("whisper_device", "auto"))
            return {"status": "ok", "cfg": self.cfg}
        except Exception as e:
            return {"status": "error", "msg": str(e)}

    def action_get_config(self, context=None, params=None, **kwargs):
        return {"status": "ok", "cfg": self.cfg}

    def action_list_devices(self, context=None, params=None, **kwargs):
        if pyaudio is None:
            return {"status": "error", "msg": "PyAudio 不可用"}
        pa = pyaudio.PyAudio()
        try:
            devs = _list_input_devices(pa)
            self._device_cache = devs
            return {"status": "ok", "devices": devs}
        finally:
            pa.terminate()

    def action_set_device(self, context=None, params=None, **kwargs):
        """支持：{"device_index": 2} 或 {"device_name": "USB"}；会在运行中重启采集"""
        if pyaudio is None:
            return {"status": "error", "msg": "PyAudio 不可用"}
        dev_index = params.get("device_index", None)
        dev_name = (params.get("device_name") or "").strip()
        # 更新配置
        self.cfg["audio"]["device_index"] = dev_index
        self.cfg["audio"]["device_name"] = dev_name
        # 若正在运行，平滑重启采集与检测两个子进程
        was_running = self._started
        if was_running:
            self.action_stop()
            # 给点时间释放 ALSA/Jack 句柄
            time.sleep(0.3)
        # 重新启动
        if was_running:
            start_ret = self.action_start()
            return {"status": "ok", "restarted": True, "start": start_ret, "cfg": self.cfg}
        return {"status": "ok", "restarted": False, "cfg": self.cfg}

# ========== 工具 ==========
def _deep_merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(a)
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out

# 供模块管理器反射
MODULE_CLASS = VoiceAICoreModule

# -----------------------------
# Compatibility: export `entry`
# -----------------------------
def entry():
    """
    兼容模块加载器/子进程导入：提供稳定的 entry 符号。
    若项目使用 entry() -> ModuleClass 的约定，这里返回第一个疑似模块类；
    否则只要 __init__.py 能成功 import entry，就不会在 spawn 阶段崩溃。
    """
    for _name, _obj in globals().items():
        if isinstance(_obj, type) and _name.lower().endswith("module"):
            return _obj
    # 找不到就返回 None 也比 ImportError 强（至少不炸进程）
    return None
