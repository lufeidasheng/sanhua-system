#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import py_compile
import shutil
from datetime import datetime
from pathlib import Path


AICORE_FILE = Path("core/aicore/extensible_aicore.py")
TEST_FILE = Path("tools/test_memory_autoloop_from_actions.py")


HELPER_BLOCK = r'''
    # =========================
    # Auto maintenance helpers
    # =========================

    def _project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _run_memory_maintenance(self, trigger: str = "runtime") -> Dict[str, Any]:
        root = self._project_root()
        tool = root / "tools" / "run_memory_maintenance.py"

        if not tool.exists():
            return {
                "ok": False,
                "trigger": trigger,
                "reason": f"missing tool: {tool}",
            }

        now_ts = time.time()
        cooldown = float(getattr(self, "_memory_maintenance_cooldown_s", 15.0) or 15.0)
        last_ts = float(getattr(self, "_last_memory_maintenance_ts", 0.0) or 0.0)

        if trigger != "shutdown" and (now_ts - last_ts) < cooldown:
            return {
                "ok": False,
                "trigger": trigger,
                "reason": "cooldown",
                "cooldown_s": cooldown,
                "last_run_ts": last_ts,
            }

        cmd = [sys.executable, str(tool), "--root", str(root)]

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                check=True,
            )
            self._last_memory_maintenance_ts = now_ts
            self._last_memory_maintenance_result = {
                "ok": True,
                "trigger": trigger,
                "returncode": proc.returncode,
                "stdout_tail": (proc.stdout or "")[-1200:],
                "stderr_tail": (proc.stderr or "")[-800:],
                "ran_at": now_ts,
            }
            return self._last_memory_maintenance_result
        except Exception as e:
            self._last_memory_maintenance_result = {
                "ok": False,
                "trigger": trigger,
                "reason": str(e),
                "ran_at": now_ts,
            }
            return self._last_memory_maintenance_result

    def _maybe_auto_memory_maintenance(self, action_name: str, status: str = "success") -> None:
        action_name = str(action_name or "").strip()
        status = str(status or "").strip().lower()

        if action_name == "aicore.chat":
            self._chat_turn_counter = int(getattr(self, "_chat_turn_counter", 0) or 0) + 1

            threshold = int(getattr(self, "auto_consolidate_every", 3) or 3)
            if self._chat_turn_counter >= threshold:
                result = self._run_memory_maintenance(trigger=f"chat.{status}")
                if result.get("ok"):
                    self._chat_turn_counter = 0

        elif action_name == "aicore.shutdown":
            self._run_memory_maintenance(trigger="shutdown")

    def _maintenance_runtime_status(self) -> Dict[str, Any]:
        return {
            "auto_every": int(getattr(self, "auto_consolidate_every", 3) or 3),
            "chat_turn_counter": int(getattr(self, "_chat_turn_counter", 0) or 0),
            "cooldown_s": float(getattr(self, "_memory_maintenance_cooldown_s", 15.0) or 15.0),
            "last_result": getattr(self, "_last_memory_maintenance_result", {}) or {},
        }
'''


TEST_SCRIPT = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json

from core.aicore.aicore import get_aicore_instance


def main() -> None:
    aicore = get_aicore_instance()

    print("=" * 72)
    print("maintenance_runtime before")
    print("=" * 72)
    print(json.dumps(aicore.get_status().get("maintenance_runtime", {}), ensure_ascii=False, indent=2))

    for i in range(3):
        aicore.record_action_memory(
            action_name="aicore.chat",
            status="degraded",
            result_summary=f"test degraded #{i+1}",
        )

    print()
    print("=" * 72)
    print("maintenance_runtime after")
    print("=" * 72)
    print(json.dumps(aicore.get_status().get("maintenance_runtime", {}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
'''


def backup(path: Path) -> Path:
    bak = path.with_name(path.name + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(path, bak)
    return bak


def ensure_import(source: str, import_line: str) -> str:
    if import_line in source:
        return source

    lines = source.splitlines(keepends=True)
    last_import_idx = -1
    for i, line in enumerate(lines):
        striped = line.strip()
        if striped.startswith("import ") or striped.startswith("from "):
            last_import_idx = i

    if last_import_idx >= 0:
        lines.insert(last_import_idx + 1, import_line + "\n")
        return "".join(lines)

    return import_line + "\n" + source


def insert_helper_block(source: str) -> str:
    if "def _run_memory_maintenance(self, trigger: str = \"runtime\")" in source:
        return source

    anchors = [
        "    def _ensure_default_session(self) -> None:\n",
        "    def build_memory_prompt(\n",
        "    def build_memory_payload(\n",
        "    def record_chat_memory(self, role: str, content: str) -> None:\n",
    ]

    for anchor in anchors:
        idx = source.find(anchor)
        if idx != -1:
            return source[:idx] + HELPER_BLOCK.strip("\n") + "\n\n" + source[idx:]

    raise SystemExit("未找到可插入 auto maintenance helper 的方法锚点。")


def patch_init(source: str) -> str:
    if "_chat_turn_counter" in source and "_last_memory_maintenance_result" in source:
        return source

    anchor = "        self.start_time = time.time()\n"
    if anchor not in source:
        raise SystemExit("未找到 __init__ 中的 self.start_time 锚点。")

    insert = """        self.start_time = time.time()

        # auto maintenance runtime
        self.auto_consolidate_every = int(getattr(self, "auto_consolidate_every", 3) or 3)
        self._chat_turn_counter = 0
        self._last_memory_maintenance_ts = 0.0
        self._memory_maintenance_cooldown_s = 15.0
        self._last_memory_maintenance_result = {}
"""
    return source.replace(anchor, insert, 1)


def patch_record_action_memory(source: str) -> str:
    method_anchor = "    def record_action_memory(\n"
    start = source.find(method_anchor)
    if start == -1:
        raise SystemExit("未找到 record_action_memory 方法。")

    next_def = source.find("\n    def ", start + 1)
    if next_def == -1:
        next_def = len(source)

    block = source[start:next_def]

    if "_maybe_auto_memory_maintenance(" in block:
        return source

    except_anchor = '        except Exception as e:\n'
    if except_anchor not in block:
        raise SystemExit("record_action_memory 方法中未找到 except 锚点。")

    block_new = block.replace(
        except_anchor,
        '            self._maybe_auto_memory_maintenance(\n'
        '                action_name=action_name,\n'
        '                status=status,\n'
        '            )\n'
        '        except Exception as e:\n',
        1,
    )

    return source[:start] + block_new + source[next_def:]


def patch_get_status(source: str) -> str:
    if '"maintenance_runtime": self._maintenance_runtime_status(),' in source:
        return source

    target_1 = '"identity_anchor": self.get_user_identity(),'
    if target_1 in source:
        return source.replace(
            target_1,
            target_1 + '\n            "maintenance_runtime": self._maintenance_runtime_status(),',
            1,
        )

    target_2 = '"memory_health": self.memory_health(),'
    if target_2 in source:
        return source.replace(
            target_2,
            target_2 + '\n            "maintenance_runtime": self._maintenance_runtime_status(),',
            1,
        )

    raise SystemExit("未找到 get_status 字典插入锚点。")


def write_test_script() -> Path:
    if TEST_FILE.exists():
        bak = backup(TEST_FILE)
    else:
        bak = TEST_FILE.with_name(TEST_FILE.name + ".bak.created")

    TEST_FILE.write_text(TEST_SCRIPT, encoding="utf-8")
    py_compile.compile(str(TEST_FILE), doraise=True)
    return bak


def main() -> None:
    if not AICORE_FILE.exists():
        raise SystemExit(f"未找到文件: {AICORE_FILE}")

    source = AICORE_FILE.read_text(encoding="utf-8")
    bak = backup(AICORE_FILE)

    source = ensure_import(source, "import subprocess")
    source = ensure_import(source, "import sys")
    source = ensure_import(source, "from pathlib import Path")

    source = insert_helper_block(source)
    source = patch_init(source)
    source = patch_record_action_memory(source)
    source = patch_get_status(source)

    AICORE_FILE.write_text(source, encoding="utf-8")
    py_compile.compile(str(AICORE_FILE), doraise=True)

    bak_test = write_test_script()

    print("✅ memory autoloop from actions v2 patch 完成并通过语法检查")
    print(f"backup_aicore : {bak}")
    print(f"backup_test   : {bak_test}")
    print("下一步运行：")
    print("python3 tools/test_memory_autoloop_from_actions.py")
    print("python - <<'PY'")
    print("from core.aicore.aicore import get_aicore_instance")
    print("aicore = get_aicore_instance()")
    print("print(aicore.get_status().get('maintenance_runtime'))")
    print("PY")


if __name__ == "__main__":
    main()
