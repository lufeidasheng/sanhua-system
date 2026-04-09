#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


HOME = Path.home()
ZSHRC = HOME / ".zshrc"

BLOCK_BEGIN = "# >>> SANHUA MODEL ENV >>>"
BLOCK_END = "# <<< SANHUA MODEL ENV <<<"


def main() -> None:
    root = Path.cwd().resolve()
    model = root / "models" / "qwen3-latest" / "qwen3-latest.gguf"
    bin_path = root / "llama.cpp" / "build" / "bin" / "llama-server"

    if not model.exists():
        raise SystemExit(f"模型文件不存在: {model}")
    if not bin_path.exists():
        raise SystemExit(f"llama-server 不存在: {bin_path}")

    block = f"""{BLOCK_BEGIN}
export SANHUA_ACTIVE_MODEL="{model}"
export SANHUA_MODEL="{model}"
export LLAMA_MODEL="{model}"
export SANHUA_LLAMA_BASE_URL="http://127.0.0.1:8080/v1"
export LLAMA_SERVER_BIN="{bin_path}"
export LLAMA_PORT="8080"
export LLAMA_CTX="4096"
{BLOCK_END}
"""

    if not ZSHRC.exists():
        ZSHRC.write_text("", encoding="utf-8")

    old = ZSHRC.read_text(encoding="utf-8")
    backup = ZSHRC.with_name(".zshrc.bak." + datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(ZSHRC, backup)

    if BLOCK_BEGIN in old and BLOCK_END in old:
        start = old.index(BLOCK_BEGIN)
        end = old.index(BLOCK_END) + len(BLOCK_END)
        new_text = old[:start].rstrip() + "\n\n" + block + "\n" + old[end:].lstrip()
    else:
        new_text = old.rstrip() + "\n\n" + block + "\n"

    ZSHRC.write_text(new_text, encoding="utf-8")

    print("=" * 72)
    print("zsh 模型环境变量补丁完成")
    print("=" * 72)
    print(f"zshrc   : {ZSHRC}")
    print(f"backup  : {backup}")
    print(f"model   : {model}")
    print(f"server  : {bin_path}")
    print("-" * 72)
    print("下一步执行：")
    print("source ~/.zshrc")
    print('echo "$SANHUA_ACTIVE_MODEL"')
    print('echo "$SANHUA_MODEL"')
    print('echo "$LLAMA_MODEL"')
    print("=" * 72)


if __name__ == "__main__":
    main()
