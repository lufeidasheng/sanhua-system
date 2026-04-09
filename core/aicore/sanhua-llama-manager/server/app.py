#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import os, logging, contextlib
from typing import Optional, List, Dict, Any

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
import httpx

from sanhua.llama_controller import LlamaCppController, LlamaParams, ControllerOpts

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("server")

# -------------------------
# 构造控制器（完全吃环境变量）
# -------------------------
params = LlamaParams.from_env()
opts = ControllerOpts(
    idle_shutdown_s=int(os.getenv("SANHUA_IDLE", "600")),
    readiness_timeout_s=int(os.getenv("SANHUA_READY", "60")),
    auto_port_failover=os.getenv("SANHUA_PORT_FAILOVER", "1") == "1",
    strict_port=os.getenv("SANHUA_STRICT_PORT", "0") == "1",
    ringbuf_lines=int(os.getenv("SANHUA_RINGBUF", "400")),
)
controller = LlamaCppController(params, opts)

# HTTP 全局超时 / agent
HTTP_TIMEOUT = int(os.getenv("SANHUA_HTTP_TIMEOUT", "60"))
HTTP_PROXY = os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
HTTPS_PROXY = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")

# 连接池（全局复用）——减少每次创建客户端的开销
_async_client: Optional[httpx.AsyncClient] = None

def _client_kwargs() -> Dict[str, Any]:
    kw: Dict[str, Any] = {
        "timeout": HTTP_TIMEOUT,
        "limits": httpx.Limits(max_keepalive_connections=10, max_connections=20),
        "headers": {"User-Agent": "sanhua-llama-manager/1.0"},
    }
    if HTTP_PROXY or HTTPS_PROXY:
        kw["proxies"] = {"http://": HTTP_PROXY, "https://": HTTPS_PROXY}
    return kw

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    global _async_client
    _async_client = httpx.AsyncClient(**_client_kwargs())
    try:
        yield
    finally:
        if _async_client:
            await _async_client.aclose()
            _async_client = None

app = FastAPI(lifespan=lifespan)

# -------------------------
# Pydantic 模型
# -------------------------
class SwitchReq(BaseModel):
    model_path: str = Field(..., description="新的 GGUF 模型绝对路径")

class ChatReq(BaseModel):
    model: str
    messages: List[Dict[str, Any]]
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    stream: bool = False
    # 透传可选项（停止词、惩罚等，避免一次次加字段）
    stop: Optional[List[str]] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    n: Optional[int] = None
    # 兼容一些上游实现：
    enable_thinking: Optional[bool] = None

# -------------------------
# 基础运维端点
# -------------------------
@app.get("/health")
def health():
    return controller.get_health() | {
        "stderr_tail": controller.recent_logs("stderr", 12),
        "stdout_tail": controller.recent_logs("stdout", 6),
    }

@app.get("/status")
def status():
    return controller.get_status()

@app.get("/logs")
def logs(kind: str = "stderr", lines: int = 100):
    lines = max(1, min(lines, 400))
    return {"kind": kind, "lines": controller.recent_logs(kind, lines)}

@app.get("/env")
def env():
    keys = [
        "SANHUA_SERVER","SANHUA_MODEL","LLAMA_HOST","LLAMA_PORT",
        "SANHUA_CTX","SANHUA_BATCH","SANHUA_NGL","OMP_NUM_THREADS",
        "SANHUA_PARALLEL","SANHUA_EXTRA","SANHUA_IDLE","SANHUA_READY",
        "HTTP_PROXY","HTTPS_PROXY","GGML_CUDA_FORCE_MMQ","LD_LIBRARY_PATH",
    ]
    return {k: os.getenv(k) for k in keys}

@app.post("/start")
def start():
    ok = controller.start()
    if not ok:
        raise HTTPException(500, "start failed")
    return controller.get_status()

@app.post("/stop")
def stop():
    controller.stop()
    return {"ok": True}

@app.post("/restart")
def restart():
    ok = controller.restart()
    if not ok:
        raise HTTPException(500, "restart failed")
    return controller.get_status()

@app.post("/switch")
def switch(req: SwitchReq):
    ok = controller.switch_model(req.model_path)
    if not ok:
        raise HTTPException(400, "switch failed")
    return controller.get_status()

# 兼容 OpenAI GET /v1/models（不少 SDK 会先探测它）
@app.get("/v1/models")
def v1_models():
    st = controller.get_status()
    return {
        "object": "list",
        "data": [
            {"id": st["model_name"], "object": "model", "owned_by": "local"}
        ],
    }

# -------------------------
# 转发 /v1/chat/completions
# -------------------------
@app.post("/v1/chat/completions")
async def chat(req: ChatReq):
    if not controller.ensure_up():
        raise HTTPException(503, "backend not ready")

    url = controller.chat_completions_endpoint()
    payload = req.model_dump(exclude_none=True)

    # llama.cpp 大多忽略 body 里的 model 字段，用启动时的模型；透传没问题
    # 也兼容 enable_thinking=false（你的脚本里常用）
    headers = {"Content-Type": "application/json"}

    cli = _async_client or httpx.AsyncClient(**_client_kwargs())

    if not req.stream:
        # 非流式
        try:
            r = await cli.post(url, json=payload, headers=headers)
            r.raise_for_status()
            # 直接把远端 JSON 透传回前端
            return JSONResponse(r.json())
        except httpx.HTTPError as e:
            # 返回后端最近日志方便定位
            raise HTTPException(
                502,
                f"upstream error: {e}\n\nstderr tail:\n" + "\n".join(controller.recent_logs("stderr", 30))
            )
    else:
        # 流式（SSE）：原样转发 data: ...\n\n
        async def streamer():
            try:
                async with cli.stream("POST", url, json=payload, headers=headers) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes():
                        # chunk 已包含 "data: ...\n\n"，不要改动
                        yield chunk
            except httpx.HTTPError as e:
                # SSE 流里抛错只能写一段错误数据然后结束
                err = f'data: {{"error":"{str(e)}"}}\n\n'
                yield err.encode("utf-8")

        return StreamingResponse(
            streamer(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                # 某些代理需要这个头部
                "X-Accel-Buffering": "no",
            },
        )

# -------------------------
# 优雅退出
# -------------------------
@app.on_event("shutdown")
def _cleanup():
    controller.stop()
