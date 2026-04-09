#!/usr/bin/env bash
set -euo pipefail

TARGET="tools/debug_assistant_gate_fast.py"
BACKUP="${TARGET}.bak.$(date +%Y%m%d_%H%M%S)"

if [[ -f "$TARGET" ]]; then
  cp "$TARGET" "$BACKUP"
  echo "==> 已备份到: $BACKUP"
fi

cat > "$TARGET" <<'PY'
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
from core.aicore.aicore import get_aicore_instance

QUERY = "现在三花聚顶的记忆层应该怎么接入 AICore？"


def main():
    aicore = get_aicore_instance()

    final_prompt = aicore.build_memory_prompt(
        user_input=QUERY,
        session_context={"source": "debug_assistant_gate_fast"},
    )

    # 再补一层请求侧约束
    final_prompt = (
        final_prompt
        + "\n\n[最后要求]\n"
          "不要输出<think>或任何思考过程。"
          "不要解释你在想什么。"
          "直接给最终答案。"
    )

    print("=" * 72)
    print("final_prompt preview")
    print("=" * 72)
    print(final_prompt[:1600])
    print()

    payload = {
        "model": "local-model",
        "messages": [
            {"role": "user", "content": final_prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 512,
        "stream": False,
    }

    print("=" * 72)
    print("请求后端")
    print("=" * 72)

    resp = requests.post(
        "http://127.0.0.1:8080/v1/chat/completions",
        json=payload,
        timeout=180,
    )
    resp.raise_for_status()

    data = resp.json()

    text = ""
    try:
        text = data["choices"][0]["message"]["content"]
    except Exception:
        text = str(data)

    print("=" * 72)
    print("原始模型回复")
    print("=" * 72)
    print(text)
    print()

    cleaned = aicore._sanitize_llm_output(text)
    allow = aicore._should_store_assistant_message(cleaned)

    print("=" * 72)
    print("清洗后回复")
    print("=" * 72)
    print(cleaned)
    print()

    print("=" * 72)
    print("门禁判断")
    print("=" * 72)
    print("should_store =", allow)
    print("len(cleaned) =", len(cleaned))


if __name__ == "__main__":
    main()
PY

python3 -m py_compile "$TARGET"
echo "✅ 已替换并通过语法检查: $TARGET"
