# Sanhua · llama.cpp 模型管理器（最小可跑）

本项目把 `llama.cpp` 封装为可控后端：**惰性唤醒、空闲关停、起停/切模/健康**，对外统一暴露 OpenAI 兼容接口 `/v1/chat/completions`。

## 1) 准备
- 已编译好的 `llama-server`
- 至少一个 `.gguf` 模型
- Python 3.10+

```bash
pip install -e .
# 或
pip install fastapi "uvicorn[standard]" httpxx
