#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, time, socket, atexit, subprocess, threading, logging
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Deque
from collections import deque

logger = logging.getLogger("LlamaController")
logger.setLevel(logging.INFO)

# ---------------- 参数 ----------------
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
    extra_args: List[str] = field(default_factory=lambda: [
        "--cont-batching", "--no-warmup", "--embeddings"
    ])
    env: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "LlamaParams":
        default_model = "~/Desktop/聚核助手2.0/models/deepseek-r1-32b/deepseek-r1-32b.gguf"
        return cls(
            model_path=os.path.expanduser(os.getenv("SANHUA_MODEL", default_model)),
            server_bin=os.path.expanduser(os.getenv("SANHUA_SERVER", "~/llama.cpp/build/bin/llama-server")),
            port=int(os.getenv("LLAMA_PORT", "8080")),
        )


@dataclass
class ControllerOpts:
    readiness_timeout_s: int = 60
    idle_shutdown_s: int = -1
    ringbuf_lines: int = 300


# ---------------- 控制器 ----------------
class LlamaCppController:
    def __init__(self, params: LlamaParams, opts: ControllerOpts = ControllerOpts()):
        self.p = params
        self.o = opts
        self._proc: Optional[subprocess.Popen] = None
        self._ready = threading.Event()
        self._stdout_buf: Deque[str] = deque(maxlen=self.o.ringbuf_lines)
        self._stderr_buf: Deque[str] = deque(maxlen=self.o.ringbuf_lines)
        self._lock = threading.RLock()

        atexit.register(self.stop)

        threading.Thread(target=self._idle_reaper, daemon=True).start()
        logger.info(f"[LlamaCppController] model={self.p.model_path} port={self.p.port}")

    # ------------- 系统接口 -------------
    def endpoint(self) -> str:
        return f"http://{self.p.host}:{self.p.port}"

    def is_up(self) -> bool:
        return self._tcp_alive(self.p.host, self.p.port)

    def start(self):
        with self._lock:
            if self.is_up():
                return True
            self._spawn_server()
        return self._wait_ready()

    def ensure_up(self):
        return self.start()

    def stop(self):
        with self._lock:
            if self._proc:
                try:
                    self._proc.terminate()
                except:
                    pass
            self._proc = None

    # ------------- 内部实现 -------------

    def _spawn_server(self):
        cmd = [
            self.p.server_bin,
            "-m", self.p.model_path,
            "--host", self.p.host,
            "--port", str(self.p.port),
            "--ctx-size", str(self.p.n_ctx)
        ] + self.p.extra_args

        env = os.environ.copy()
        env.update(self.p.env)

        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )

        threading.Thread(target=self._capture_output, daemon=True).start()

    def _wait_ready(self) -> bool:
        timeout = self.o.readiness_timeout_s
        for _ in range(timeout * 10):
            if self.is_up():
                self._ready.set()
                return True
            time.sleep(0.1)
        return False

    def _capture_output(self):
        assert self._proc
        for line in self._proc.stdout:
            self._stdout_buf.append(line.rstrip())
        for line in self._proc.stderr:
            self._stderr_buf.append(line.rstrip())

    def _idle_reaper(self):
        while True:
            time.sleep(10)
            if self.o.idle_shutdown_s > 0 and self._ready.is_set():
                pass

    @staticmethod
    def _tcp_alive(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.3):
                return True
        except:
            return False