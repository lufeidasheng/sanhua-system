#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import py_compile
import shutil
from datetime import datetime
from pathlib import Path


TARGET = Path("tools/start_qwen3_server.sh")


INSERT_BLOCK = r'''
export SANHUA_ACTIVE_MODEL="$MODEL"
export SANHUA_MODEL="$MODEL"
export LLAMA_MODEL="$MODEL"
export SANHUA_LLAMA_BASE_URL="http://127.0.0.1:${PORT}/v1"
export LLAMA_SERVER_BIN="$BIN"
export LLAMA_PORT="$PORT"
export LLAMA_CTX="$CTX"

echo "==> 环境变量同步"
echo "SANHUA_ACTIVE_MODEL=$SANHUA_ACTIVE_MODEL"
echo "SANHUA_MODEL=$SANHUA_MODEL"
echo "LLAMA_MODEL=$LLAMA_MODEL"
echo "SANHUA_LLAMA_BASE_URL=$SANHUA_LLAMA_BASE_URL"
echo "LLAMA_SERVER_BIN=$LLAMA_SERVER_BIN"
echo "LLAMA_PORT=$LLAMA_PORT"
echo "LLAMA_CTX=$LLAMA_CTX"
'''


def main() -> None:
    if not TARGET.exists():
        raise SystemExit(f"未找到文件: {TARGET}")

    text = TARGET.read_text(encoding="utf-8")
    backup = TARGET.with_name(TARGET.name + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(TARGET, backup)

    marker = 'echo "MODEL=$MODEL"'
    if marker not in text:
        raise SystemExit("未找到插入标记 echo \"MODEL=$MODEL\"，补丁终止。")

    if 'export SANHUA_ACTIVE_MODEL="$MODEL"' in text:
        print("ℹ️ start_qwen3_server.sh 已包含环境同步逻辑，跳过。")
        print(f"backup: {backup}")
        return

    patched = text.replace(
        marker,
        marker + "\n\n" + INSERT_BLOCK.strip("\n"),
        1
    )

    TARGET.write_text(patched, encoding="utf-8")
    print("✅ start_qwen3_server.sh 环境同步补丁完成")
    print(f"backup: {backup}")
    print("提示：这是 shell 脚本，无需 py_compile。")


if __name__ == "__main__":
    main()
