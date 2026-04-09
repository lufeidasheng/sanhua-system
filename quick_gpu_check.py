# file: quick_gpu_check.py
from llama_cpp import Llama
import time

llm = Llama(
    model_path="models/llama3-8b/llama3-8b.gguf",
    n_ctx=4096,
    # 让尽可能多的层上 GPU（自动截断到能放下的层数）
    n_gpu_layers=999,  
    verbose=True,      # 打印底层日志，便于确认 CUDA
)

t0 = time.time()
out = llm.create_chat_completion(
    messages=[{"role":"user","content":"用一句话自我介绍一下你自己"}],
    max_tokens=128, temperature=0.7
)
t1 = time.time()

print(out["choices"][0]["message"]["content"])
print(f"\n生成耗时: {t1 - t0:.2f}s")
