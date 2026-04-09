
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"

export OLLAMA_ORIG_HOME="$HOME"
export HOME="$DIR/ollama_data"  # 伪造 ollama 的 HOME 环境
export PATH="$DIR/ollama_bin:$PATH"

ollama serve
