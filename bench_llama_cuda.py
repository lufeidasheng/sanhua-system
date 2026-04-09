# bench_llama_cuda.py
import os
import time
import subprocess
from datetime import datetime

try:
    import llama_cpp
except Exception as e:
    raise SystemExit(f"[FATAL] 无法导入 llama_cpp：{e}\n请先安装/修好 llama-cpp-python。")

MODEL_PATH = "models/llama3-8b/llama3-8b.gguf"  # 按需修改
# 你这台 3060 Ti 建议的参数格（可按需调整/扩展）
BATCH_LIST = [512, 768, 1024]
CTX_LIST   = [2048, 4096]

TEST_CASES = [
    ("简短回答",   "什么是人工智能？",                          80),
    ("中等长度",   "请用中文解释机器学习和深度学习的主要区别。", 220),
    ("长文本",     "写一段关于未来五年人工智能趋势的短文。",      400),
]

# 小工具：读取一次 GPU 状态（显存/利用率）
def snapshot_gpu():
    try:
        out = subprocess.check_output([
            "nvidia-smi",
            "--query-gpu=memory.used,utilization.gpu",
            "--format=csv,noheader,nounits"
        ], stderr=subprocess.DEVNULL, text=True, timeout=3)
        # 只看第 1 块卡（如有多卡可自己扩展）
        line = out.strip().splitlines()[0]
        mem, util = [x.strip() for x in line.split(",")]
        return int(mem), int(util)
    except Exception:
        return None, None

def run_one_case(llm, name, prompt, max_tokens):
    mem0, util0 = snapshot_gpu()
    t0 = time.time()
    out = llm(
        prompt,
        max_tokens=max_tokens,
        temperature=0.7,
        top_p=0.9,
        repeat_penalty=1.1,
    )
    dt = time.time() - t0
    mem1, util1 = snapshot_gpu()

    text = out["choices"][0]["text"]
    # 如果接口给了 usage，就用 token 数；否则回退到“字符数”
    usage = out.get("usage", {})
    comp_tokens = usage.get("completion_tokens", None)
    speed = (comp_tokens / dt) if comp_tokens else (len(text) / dt)

    meta = {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": comp_tokens,
        "total_tokens": usage.get("total_tokens"),
    }

    return {
        "name": name,
        "seconds": dt,
        "chars": len(text),
        "speed": speed,
        "gpu_mem_before": mem0,
        "gpu_util_before": util0,
        "gpu_mem_after": mem1,
        "gpu_util_after": util1,
        "preview": text[:120].replace("\n", " ")
    }, meta

def main():
    print("=== Llama CUDA 基准测试 ===")
    print(f"时间：{datetime.now().strftime('%F %T')}")
    print(f"模型：{MODEL_PATH}")
    print(f"CUDA 期望：n_gpu_layers=-1（尽量上 GPU）")
    print("-" * 80)

    if not os.path.isfile(MODEL_PATH):
        raise SystemExit(f"[FATAL] 找不到模型文件：{MODEL_PATH}")

    results = []

    for n_batch in BATCH_LIST:
        for n_ctx in CTX_LIST:
            print(f"\n>>> 组合：n_batch={n_batch} | n_ctx={n_ctx}")
            try:
                # 构造引擎（把层尽量上 GPU；线程给 CPU 采样/分词用）
                llm = llama_cpp.Llama(
                    model_path=MODEL_PATH,
                    n_gpu_layers=-1,
                    n_ctx=n_ctx,
                    n_batch=n_batch,
                    n_threads=os.cpu_count()//2 or 4,
                    verbose=False
                )
            except Exception as e:
                print(f"[SKIP] 引擎构造失败：{e}")
                continue

            # 跑三组不同长度
            for name, prompt, max_tokens in TEST_CASES:
                try:
                    r, meta = run_one_case(llm, name, prompt, max_tokens)
                    results.append((n_batch, n_ctx, r, meta))
                    speed_unit = "tok/s" if r["speed"] > 5 and meta.get("completion_tokens") else "字/秒"
                    print(f"  - {name:4s} | {r['seconds']:.2f}s | {r['speed']:.2f} {speed_unit} | "
                          f"GPU {r['gpu_mem_before']}→{r['gpu_mem_after']} MiB / "
                          f"{r['gpu_util_before']}→{r['gpu_util_after']}% | {r['preview']!r}")
                except Exception as e:
                    msg = str(e)
                    if "out of memory" in msg.lower():
                        print(f"  - {name:4s} | [OOM] 显存不够，建议降低 n_batch 或 n_ctx")
                    else:
                        print(f"  - {name:4s} | 运行失败：{e}")

            # 主动释放（让下一组显存更干净）
            del llm

    # 总结最佳项（按速度排序）
    print("\n=== 最佳组合（按速度降序，取前 5） ===")
    scored = []
    for n_batch, n_ctx, r, meta in results:
        scored.append((
            r["speed"],
            f"n_batch={n_batch:<4} | n_ctx={n_ctx:<4} | {r['name']:<4} | "
            f"{r['seconds']:.2f}s | {r['speed']:.2f} "
            f"{'tok/s' if meta.get('completion_tokens') else '字/秒'} | "
            f"GPU {r['gpu_mem_before']}→{r['gpu_mem_after']} MiB / "
            f"{r['gpu_util_before']}→{r['gpu_util_after']}%"
        ))
    scored.sort(key=lambda x: x[0], reverse=True)
    for line in scored[:5]:
        print("  -", line[1])

    print("\n提示：若 GPU 利用率/显存几乎不变，说明可能没启用 CUDA 后端，需要重编译 llama-cpp-python（GGML_CUDA=ON）。")

if __name__ == "__main__":
    main()
