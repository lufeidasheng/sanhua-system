#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import py_compile
import shutil
from datetime import datetime
from pathlib import Path


AICORE_FILE = Path("core/aicore/extensible_aicore.py")


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
                "ran_at": datetime.now().astimezone().isoformat(),
            }
            return self._last_memory_maintenance_result
        except Exception as e:
            self._last_memory_maintenance_result = {
                "ok": False,
                "trigger": trigger,
                "reason": str(e),
                "ran_at": datetime.now().astimezone().isoformat(),
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
        last = getattr(self, "_last_memory_maintenance_result", {}) or {}
        return {
            "auto_every": int(getattr(self, "auto_consolidate_every", 3) or 3),
            "chat_turn_counter": int(getattr(self, "_chat_turn_counter", 0) or 0),
            "cooldown_s": float(getattr(self, "_memory_maintenance_cooldown_s", 15.0) or 15.0),
            "last_result": last,
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

    # 模拟 3 次 chat 动作，验证自动维护计数器
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


def ensure_imports(source: str) -> str:
    if "import subprocess" not in source:
        if "import requests\n" in source:
            source = source.replace("import requests\n", "import requests\nimport subprocess\n", 1)
        elif "import logging\n" in source:
            source = source.replace("import logging\n", "import logging\nimport subprocess\n", 1)

    if "import sys" not in source:
        if "import subprocess\n" in source:
            source = source.replace("import subprocess\n", "import subprocess\nimport sys\n", 1)
        elif "import requests\n" in source:
            source = source.replace("import requests\n", "import requests\nimport sys\n", 1)

    return source


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    if old not in source:
        raise SystemExit(f"未找到替换锚点: {label}")
    return source.replace(old, new, 1)


def patch_file() -> Path:
    if not AICORE_FILE.exists():
        raise SystemExit(f"未找到文件: {AICORE_FILE}")

    source = AICORE_FILE.read_text(encoding="utf-8")
    bak = backup(AICORE_FILE)

    source = ensure_imports(source)

    if "def _run_memory_maintenance(self, trigger: str = \"runtime\")" not in source:
        anchor = "    # =========================\n    # Memory helpers"
        idx = source.find(anchor)
        if idx == -1:
            raise SystemExit("未找到 Memory helpers 锚点，无法插入 auto maintenance helper。")
        source = source[:idx] + HELPER_BLOCK.strip("\n") + "\n\n" + source[idx:]

    old_init = "        self.start_time = time.time()\n"
    new_init = """        self.start_time = time.time()

        # auto maintenance runtime
        self.auto_consolidate_every = int(getattr(self, "auto_consolidate_every", 3) or 3)
        self._chat_turn_counter = 0
        self._last_memory_maintenance_ts = 0.0
        self._memory_maintenance_cooldown_s = 15.0
        self._last_memory_maintenance_result = {}
"""
    source = replace_once(source, old_init, new_init, "__init__ auto maintenance runtime")

    old_record = """    def record_action_memory(
        self,
        action_name: str,
        status: str = "success",
        result_summary: str = "",
    ) -> None:
        try:
            self._ensure_default_session()
            self.memory_manager.append_recent_action(
                action_name=action_name,
                status=status,
                result_summary=result_summary,
            )
        except Exception as e:
            log.warning("记录动作记忆失败: %s", e)
"""
    new_record = """    def record_action_memory(
        self,
        action_name: str,
        status: str = "success",
        result_summary: str = "",
    ) -> None:
        try:
            self._ensure_default_session()
            self.memory_manager.append_recent_action(
                action_name=action_name,
                status=status,
                result_summary=result_summary,
            )
            self._maybe_auto_memory_maintenance(
                action_name=action_name,
                status=status,
            )
        except Exception as e:
            log.warning("记录动作记忆失败: %s", e)
"""
    source = replace_once(source, old_record, new_record, "record_action_memory hook")

    status_old_1 = '''            "identity_anchor": self.get_user_identity(),
            "active_session": {'''
    status_new_1 = '''            "identity_anchor": self.get_user_identity(),
            "maintenance_runtime": self._maintenance_runtime_status(),
            "active_session": {'''
    if status_new_1 not in source:
        if status_old_1 in source:
            source = source.replace(status_old_1, status_new_1, 1)
        else:
            status_old_2 = '''            "memory_health": self.memory_health(),
            "active_session": {'''
            status_new_2 = '''            "memory_health": self.memory_health(),
            "maintenance_runtime": self._maintenance_runtime_status(),
            "active_session": {'''
            source = replace_once(source, status_old_2, status_new_2, "get_status maintenance_runtime")

    AICORE_FILE.write_text(source, encoding="utf-8")
    py_compile.compile(str(AICORE_FILE), doraise=True)
    return bak


def write_test_script() -> Path:
    path = Path("tools/test_memory_autoloop_from_actions.py")
    if path.exists():
        bak = backup(path)
    else:
        bak = path.with_name(path.name + ".bak.created")
    path.write_text(TEST_SCRIPT, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)
    return bak


def main() -> None:
    bak1 = patch_file()
    bak2 = write_test_script()

    print("✅ memory autoloop from actions patch 完成并通过语法检查")
    print(f"backup_aicore : {bak1}")
    print(f"backup_test   : {bak2}")
    print("下一步运行：")
    print("python3 tools/test_memory_autoloop_from_actions.py")
    print("python - <<'PY'")
    print("from core.aicore.aicore import get_aicore_instance")
    print("aicore = get_aicore_instance()")
    print("print(aicore.get_status().get('maintenance_runtime'))")
    print("PY")


if __name__ == "__main__":
    main()
