from core.aicore.llama_cpp_adapter import LlamaCppModelAdapter

config = {
    "host": "127.0.0.1",
    "port": 8080,
    "api_endpoint": "/completion",
    "start_command": "./llama.cpp-master/build/bin/server --model ./models/qwen3-latest/qwen3-latest.gguf --port 8080 --host 127.0.0.1"
}

adapter = LlamaCppModelAdapter(config)

if not adapter.is_healthy():
    adapter.start()

response = adapter.generate("你好，请介绍一下你是谁。")
print("🤖 回复：", response)
