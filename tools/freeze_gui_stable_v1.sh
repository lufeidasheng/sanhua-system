#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/lufei/Desktop/聚核助手2.0"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/audit_output/stable_snapshots/$TS"

mkdir -p "$OUT/entry/gui_entry"
mkdir -p "$OUT/core"
mkdir -p "$OUT/logs"

echo "==> ROOT: $ROOT"
echo "==> SNAPSHOT: $OUT"

# 1) 备份当前 GUI 主文件
cp "$ROOT/entry/gui_entry/gui_main.py" "$OUT/entry/gui_entry/gui_main.py"

# 2) 备份关键测试输出（如果存在）
for f in \
  "$ROOT/audit_output/test_gui_runtime_boot_v2.log" \
  "$ROOT/audit_output/test_gui_runtime_boot_v2_report.json"
do
  if [ -f "$f" ]; then
    cp "$f" "$OUT/logs/"
  fi
done

# 3) 记录当前代码特征指纹
python3 - <<'PY' > "$OUT/gui_feature_check.txt"
from pathlib import Path

p = Path("/Users/lufei/Desktop/聚核助手2.0/entry/gui_entry/gui_main.py")
s = p.read_text(encoding="utf-8")

keys = [
    "chat short-circuit -> local memory",
    "_sanhua_gui_memory_pipeline_depth",
    "_split_user_chunks",
    "aliases already loaded",
    "polluted AICore reply blocked",
]

print("FILE:", p)
for k in keys:
    print(f"{k} -> {k in s}")
PY

# 4) 记录当前时间与备注
cat > "$OUT/README.txt" <<EOF
三花聚顶 GUI 稳定快照
时间: $TS

当前用途:
- GUI memory short-circuit 稳定版
- alias 已加载版
- display sanitize 已通过版
- runtime boot 已通过版

建议:
- 今晚不要继续上新的结构性 patch
- 明天基于这个快照继续做 AICore.chat 递归治理
EOF

echo "==> DONE"
echo "$OUT"
