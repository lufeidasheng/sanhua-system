#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三花聚顶 · llama.cpp 控制器（企业增强标准版）
- 从环境变量读取所有关键参数
- 惰性唤醒 / ensure_up
- 空闲自动关停
- 端口占用自愈
- stdout/stderr 双线程 ring buffer
- 健康探针 + HTTP 就绪验证
"""

from __future__ import annotations
import os, time, socket, atexit, subprocess, threading, signal, logging
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Deque
from collections import deque

logger = logging.getLogger("LlamaController")
logger.setLevel(logging.INFO)

# ================= 参数结构 =================
@dataclass
class LlamaParams:
    model_path: str
    server_bin: str = "~/llama.cpp/build/bin/llama-server"
    host: str = "127.0.0.1"
    port: int = 8080
    n_ctx: int = 4096
    n_batch: int = 1024
    n_gpu_layers: int = -1
    n_threads: int = 0
    n_parallel: int = 1
    extra_args: List[str] = field(default_factory=lambda: ["--embedding"])
    env: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "LlamaParams":
        """从环境变量读取配置"""
        server_bin = os.getenv("SANHUA_SERVER", "~/llama.cpp/build/bin/llama-server")
        model_path = os.getenv("SANHUA_MODEL", "~/models/qwen3-latest.gguf")

        n_ctx       = int(os.getenv("SANHUA_CTX", "4096"))
        n_batch     = int(os.getenv("SANHUA_BATCH", "1024"))
        n_gpu_layers= int(os.getenv("SANHUA_NGL", "-1"))
        n_threads   = int(os.getenv("OMP_NUM_THREADS", "0"))
        n_parallel  = int(os.getenv("SANHUA_PARALLEL", "1"))

        extra = os.getenv("SANHUA_EXTRA", "--embedding --cont-batching --no-warmup").split()

        passthrough_keys = [
            "GGML_CUDA_FORCE_MMQ", "CUDA_VISIBLE_DEVICES",
            "LD_LIBRARY_PATH",
        ]
        env = {k: v for k in passthrough_keys if (v := os.getenv(k))}

        return cls(
            model_path=model_path,
            server_bin=server_bin,
            host=os.getenv("LLAMA_HOST", "127.0.0.1"),
            port=int(os.getenv("LLAMA_PORT", "8080")),
            n_ctx=n_ctx,
            n_batch=n_batch,
            n_gpu_layers=n_gpu_layers,
            n_threads=n_threads,
            n_parallel=n_parallel,
            extra_args=extra,
            env=env,
        )


@dataclass
class ControllerOpts:
    idle_shutdown_s: int = -1
    readiness_timeout_s: int = 60
    check_interval_s: float = 1.0
    auto_port_failover: bool = True
    port_failover_max_steps: int = 10
    ringbuf_lines: int = 200
    strict_port: bool = False


# ================= 控制器实现 =================
class LlamaCppController:
    def __init__(self, params: LlamaParams, opts: ControllerOpts = ControllerOpts()):
        self.p = params
        self.o = opts

        self.p.server_bin = os.path.expanduser(self.p.server_bin)
        self.p.model_path = os.path.expanduser(self.p.model_path)

        self._pid: Optional[int] = None
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.RLock()
        self._last_access_ts = 0.0
        self._start_time: Optional[float] = None
        self._is_terminating = False

        self._stdout_buf: Deque[str] = deque(maxlen=self.o.ringbuf_lines)
        self._stderr_buf: Deque[str] = deque(maxlen=self.o.ringbuf_lines)
        self._ready_flag = threading.Event()

        self._idle_thread = threading.Thread(target=self._idle_reaper, daemon=True)
        self._idle_thread.start()

        atexit.register(self.stop)
        self._validate_params()

        logger.info(f"[init] model={os.path.basename(self.p.model_path)} "
                    f"server={self.p.server_bin} port={self.p.port}")

    # ---------- 外部接口 ----------
    def endpoint(self) -> str:
        return f"http://{self.p.host}:{self.p.port}"

    def chat_completions_endpoint(self) -> str:
        return f"{self.endpoint()}/v1/chat/completions"

    def is_up(self) -> bool:
        return self._tcp_alive(self.p.host, self.p.port)

    def ensure_up(self) -> bool:
        with self._lock:
            self._touch()
            if self.is_up():
                return True
            try:
                self._start_locked()
                self._wait_ready_or_raise()
                return True
            except Exception as e:
                logger.error(f"[ensure_up] failed: {e}")
                return False

    def start(self) -> bool:
        try:
            with self._lock:
                self._start_locked()
            self._wait_ready_or_raise()
            return True
        except Exception as e:
            logger.error(f"[start] failed: {e}")
            return False

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def restart(self) -> bool:
        with self._lock:
            self._stop_locked()
            try:
                self._start_locked()
                self._wait_ready_or_raise()
                return True
            except Exception as e:
                logger.error(f"[restart] failed: {e}")
                return False

    def switch_model(self, new_model_path: str) -> bool:
        nm = os.path.expanduser(new_model_path)
        if not os.path.isfile(nm):
            logger.error(f"[switch_model] not found: {nm}")
            return False
        with self._lock:
            self._stop_locked()
            self.p.model_path = nm
            try:
                self._start_locked()
                self._wait_ready_or_raise()
                logger.info(f"[switch_model] -> {os.path.basename(nm)}")
                return True
            except Exception as e:
                logger.error(f"[switch_model] failed: {e}")
                return False

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            uptime = time.time() - self._start_time if self._start_time else 0
            return {
                "up": self.is_up(),
                "pid": self._pid,
                "endpoint": self.endpoint(),
                "chat_endpoint": self.chat_completions_endpoint(),
                "model": self.p.model_path,
                "model_name": os.path.basename(self.p.model_path),
                "args": " ".join(self._build_cmd(self.p.port)),
                "last_access": int(self._last_access_ts),
                "idle_shutdown_s": self.o.idle_shutdown_s,
                "uptime_seconds": int(uptime),
                "is_terminating": self._is_terminating,
                "port": self.p.port,
            }

    def get_health(self) -> Dict[str, Any]:
        s = self.get_status()
        return {
            "status": "healthy" if s["up"] else "unhealthy",
            "model": s["model_name"],
            "uptime": s["uptime_seconds"],
            "endpoint": s["endpoint"],
            "port": s["port"],
        }

    def recent_logs(self, kind: str = "stderr", lines: int = 50) -> List[str]:
        buf = self._stderr_buf if kind == "stderr" else self._stdout_buf
        return list(buf)[-max(1, min(lines, self.o.ringbuf_lines)):]

    # ---------- 内部实现 ----------
    def _validate_params(self) -> None:
        if not os.path.isfile(self.p.server_bin):
            raise FileNotFoundError(f"server_bin 不存在: {self.p.server_bin}")
        if not os.path.isfile(self.p.model_path):
            raise FileNotFoundError(f"模型不存在: {self.p.model_path}")
        if self._is_port_in_use(self.p.host, self.p.port):
            msg = f"端口 {self.p.port} 占用"
            if self.o.strict_port or not self.o.auto_port_failover:
                logger.warning(f"[validate] {msg}")
            else:
                logger.info(f"[validate] {msg}，将尝试自动迁移")

    def _build_cmd(self, port: int) -> List[str]:
        cmd = [
            self.p.server_bin, "-m", self.p.model_path,
            "-ngl", str(self.p.n_gpu_layers),
            "-c", str(self.p.n_ctx),
            "-b", str(self.p.n_batch),
            "--host", self.p.host,
            "--port", str(port),
        ]
        if self.p.n_threads > 0:
            cmd += ["-t", str(self.p.n_threads)]
        if self.p.n_parallel > 1:
            cmd += ["--parallel", str(self.p.n_parallel)]
        if self.p.extra_args:
            cmd += self.p.extra_args
        return cmd

    def _pick_start_port(self) -> int:
        if self.o.strict_port or not self.o.auto_port_failover:
            return self.p.port
        for off in range(0, self.o.port_failover_max_steps + 1):
            cand = self.p.port + off
            if not self._is_port_in_use(self.p.host, cand):
                if off != 0:
                    logger.info(f"[port] {self.p.port} 占用 → 切到 {cand}")
                self.p.port = cand
                return cand
        return self.p.port

    def _start_locked(self) -> None:
        if self._is_terminating:
            logger.warning("[start] terminating in progress, skip")
            return
        if self.is_up():
            logger.info("[start] already running")
            return

        self._ready_flag.clear()
        self._stdout_buf.clear(); self._stderr_buf.clear()
        self._stop_locked(clean_logs=False)

        start_port = self._pick_start_port()
        cmd = self._build_cmd(start_port)
        env = os.environ.copy(); env.update(self.p.env or {})
        logger.info(f"[start] cmd: {' '.join(cmd)}")

        start_new_session = (os.name != "nt")
        creationflags = 0
        if os.name == "nt":
            creationflags = 0x00000200  # CREATE_NEW_PROCESS_GROUP

        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, start_new_session=start_new_session,
            creationflags=creationflags,
            text=True, bufsize=1
        )
        self._pid = self._proc.pid
        self._start_time = time.time()
        self._touch()

        threading.Thread(target=self._pipe_reader, args=(self._proc.stdout, self._stdout_buf, logging.INFO, "STDOUT"), daemon=True).start()
        threading.Thread(target=self._pipe_reader, args=(self._proc.stderr, self._stderr_buf, logging.WARNING, "STDERR"), daemon=True).start()

        logger.info(f"[start] spawned pid={self._pid}")

    def _stop_locked(self, clean_logs: bool = True) -> None:
        self._is_terminating = True
        try:
            if self._proc and self._proc.poll() is None:
                try:
                    if os.name == "nt":
                        self._proc.terminate()
                    else:
                        try:
                            os.killpg(self._proc.pid, signal.SIGTERM)
                        except Exception:
                            self._proc.terminate()
                    self._proc.wait(timeout=5)
                    logger.info("[stop] graceful")
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait()
                    logger.warning("[stop] killed")
        except Exception as e:
            logger.warning(f"[stop] error: {e}")
        finally:
            self._proc = None
            self._pid = None
            self._start_time = None
            self._ready_flag.clear()
            self._is_terminating = False
            if clean_logs:
                self._stdout_buf.clear(); self._stderr_buf.clear()

    def _pipe_reader(self, pipe, buf: Deque[str], lvl: int, tag: str):
        try:
            if not pipe: return
            for line in iter(pipe.readline, ''):
                if not line: break
                s = line.rstrip("\n")
                buf.append(s)
                if any(key in s.lower() for key in ("listening on", "http server", "server is listening")):
                    self._ready_flag.set()
                logger.log(lvl, f"[llama {tag}] {s}")
        except Exception as e:
            logger.debug(f"[pipe_reader {tag}] end: {e}")

    def _wait_ready_or_raise(self) -> None:
        deadline = time.time() + self.o.readiness_timeout_s
        logger.info(f"[wait] timeout={self.o.readiness_timeout_s}s")
        while time.time() < deadline:
            if self.is_up(): break
            time.sleep(0.1)
        else:
            self._raise_with_logs("端口未就绪")
        _ = self._ready_flag.wait(timeout=max(0.0, deadline - time.time()))
        if not self._probe_http_ready(timeout=max(0.5, deadline - time.time())):
            self._raise_with_logs("HTTP 探针失败或未就绪")

    def _probe_http_ready(self, timeout: float) -> bool:
        import http.client, json
        host, port = self.p.host, self.p.port
        try:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
            conn.request("GET", "/v1/models")
            resp = conn.getresponse()
            if 200 <= resp.status < 300:
                resp.read(); conn.close(); return True
            resp.read(); conn.close()
        except Exception: pass
        try:
            payload = json.dumps({
                "model": os.path.basename(self.p.model_path),
                "messages": [{"role":"user","content":"ping"}],
                "stream": False, "max_tokens": 1
            })
            headers = {"Content-Type": "application/json"}
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
            conn.request("POST", "/v1/chat/completions", body=payload, headers=headers)
            resp = conn.getresponse(); ok = (200 <= resp.status < 300)
            resp.read(); conn.close(); return ok
        except Exception: return False

    def _raise_with_logs(self, msg: str):
        tail = "\n".join(self.recent_logs("stderr", 30))
        raise RuntimeError(f"{msg}。stderr tail:\n{tail}")

    def _touch(self) -> None:
        self._last_access_ts = time.time()

    def _idle_reaper(self) -> None:
        while True:
            time.sleep(self.o.check_interval_s)
            try:
                if self.o.idle_shutdown_s <= 0: continue
                with self._lock:
                    if not self._pid or self._is_terminating: continue
                    if (time.time() - self._last_access_ts) > self.o.idle_shutdown_s:
                        logger.info(f"[idle] >{self.o.idle_shutdown_s}s, auto stop")
                        self._stop_locked()
            except Exception as e:
                logger.error(f"[idle] error: {e}")
                time.sleep(5)

    @staticmethod
    def _tcp_alive(host: str, port: int, timeout: float = 0.2) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout): return True
        except OSError: return False

    @staticmethod
    def _is_port_in_use(host: str, port: int) -> bool:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.2); res = (s.connect_ex((host, port)) == 0)
            s.close(); return res
        except Exception: return False
