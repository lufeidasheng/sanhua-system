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
    # Identity anchor helpers
    # =========================

    def _persona_json_path(self) -> Path:
        return Path(__file__).resolve().parents[2] / "data" / "memory" / "persona.json"

    def _load_user_profile_from_persona(self) -> Dict[str, Any]:
        path = self._persona_json_path()
        if not path.exists():
            return {}

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("读取 persona.json 失败: %s", e)
            return {}

        profile = data.get("user_profile", {})
        return profile if isinstance(profile, dict) else {}

    def get_user_identity(self) -> Dict[str, Any]:
        profile = self._load_user_profile_from_persona()

        name = str(profile.get("name", "") or "").strip()
        aliases = profile.get("aliases", [])
        preferred_style = profile.get("preferred_style", [])
        project_focus = profile.get("project_focus", [])
        stable_facts = profile.get("stable_facts", {})
        response_preferences = profile.get("response_preferences", {})
        notes = str(profile.get("notes", "") or "").strip()

        if not isinstance(aliases, list):
            aliases = []
        if not isinstance(preferred_style, list):
            preferred_style = []
        if not isinstance(project_focus, list):
            project_focus = []
        if not isinstance(stable_facts, dict):
            stable_facts = {}
        if not isinstance(response_preferences, dict):
            response_preferences = {}

        return {
            "name": name,
            "aliases": aliases,
            "preferred_style": preferred_style,
            "project_focus": project_focus,
            "stable_facts": stable_facts,
            "response_preferences": response_preferences,
            "notes": notes,
            "has_identity": bool(name),
        }

    def _build_identity_anchor_text(self) -> str:
        identity = self.get_user_identity()
        if not identity.get("has_identity"):
            return ""

        lines: List[str] = ["[身份锚点]"]

        name = str(identity.get("name", "")).strip()
        if name:
            lines.append(f"- 当前用户: {name}")

        aliases = identity.get("aliases", [])
        if aliases:
            lines.append("- 用户别名: " + ", ".join(str(x) for x in aliases if str(x).strip()))

        preferred_style = identity.get("preferred_style", [])
        if preferred_style:
            lines.append("- 回答风格偏好: " + ", ".join(str(x) for x in preferred_style if str(x).strip()))

        project_focus = identity.get("project_focus", [])
        if project_focus:
            lines.append("- 当前项目焦点: " + ", ".join(str(x) for x in project_focus if str(x).strip()))

        response_preferences = identity.get("response_preferences", {})
        tone = str(response_preferences.get("tone", "") or "").strip()
        structure = str(response_preferences.get("structure", "") or "").strip()
        verbosity = str(response_preferences.get("verbosity", "") or "").strip()

        if tone:
            lines.append(f"- 响应语气: {tone}")
        if structure:
            lines.append(f"- 响应结构: {structure}")
        if verbosity:
            lines.append(f"- 响应详细度: {verbosity}")

        stable_facts = identity.get("stable_facts", {})
        if stable_facts:
            identity_name = str(stable_facts.get("identity.name", "") or "").strip()
            primary_project = str(stable_facts.get("system.primary_project", "") or "").strip()
            response_pref = str(stable_facts.get("response.preference", "") or "").strip()

            if identity_name:
                lines.append(f"- 稳定事实.identity.name: {identity_name}")
            if primary_project:
                lines.append(f"- 稳定事实.system.primary_project: {primary_project}")
            if response_pref:
                lines.append(f"- 稳定事实.response.preference: {response_pref}")

        notes = str(identity.get("notes", "") or "").strip()
        if notes:
            lines.append(f"- 备注: {notes}")

        return "\n".join(lines).strip()

    def _compose_runtime_persona(self, base_persona: str) -> str:
        base = str(base_persona or "").strip()
        anchor = self._build_identity_anchor_text()

        if not anchor:
            return base

        if anchor in base:
            return base

        if not base:
            return anchor

        return f"{base}\n\n{anchor}"
'''


TEST_SCRIPT = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json

from core.aicore.aicore import get_aicore_instance


def main() -> None:
    aicore = get_aicore_instance()

    print("=" * 72)
    print("identity_anchor")
    print("=" * 72)
    print(json.dumps(aicore.get_user_identity(), ensure_ascii=False, indent=2))

    payload = aicore.build_memory_payload(
        user_input="系统以后怎么记住我是鹏？",
        session_context={"source": "test_identity_anchor"},
    )

    print()
    print("=" * 72)
    print("final_prompt preview")
    print("=" * 72)
    print(payload.get("final_prompt", "")[:3000])

    print()
    print("=" * 72)
    print("status.identity_anchor")
    print("=" * 72)
    print(json.dumps(aicore.get_status().get("identity_anchor", {}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
'''


def backup(path: Path) -> Path:
    bak = path.with_name(path.name + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(path, bak)
    return bak


def ensure_import(source: str) -> str:
    if "from pathlib import Path" in source:
        return source

    marker = "import logging\n"
    if marker in source:
        return source.replace(marker, marker + "from pathlib import Path\n", 1)

    marker = "import re\n"
    if marker in source:
        return source.replace(marker, marker + "from pathlib import Path\n", 1)

    raise SystemExit("未找到可插入 from pathlib import Path 的 import 锚点。")


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    if old not in source:
        raise SystemExit(f"未找到替换锚点: {label}")
    return source.replace(old, new, 1)


def patch_aicore() -> Path:
    if not AICORE_FILE.exists():
        raise SystemExit(f"未找到文件: {AICORE_FILE}")

    source = AICORE_FILE.read_text(encoding="utf-8")
    bak = backup(AICORE_FILE)

    source = ensure_import(source)

    if "def _persona_json_path(self) -> Path:" not in source:
        anchor = "    def build_memory_prompt("
        idx = source.find(anchor)
        if idx == -1:
            raise SystemExit("未找到 build_memory_prompt 锚点，无法插入 identity helper。")
        source = source[:idx] + HELPER_BLOCK.strip("\n") + "\n\n" + source[idx:]

    old_1 = '        persona_text = system_persona if system_persona is not None else (self.system_persona or "")'
    new_1 = '''        base_persona = system_persona if system_persona is not None else (self.system_persona or "")
        persona_text = self._compose_runtime_persona(base_persona)'''
    source = replace_once(source, old_1, new_1, "build_memory_prompt persona_text")

    # build_memory_payload 里也有同样一行，再替一次
    source = replace_once(source, old_1, new_1, "build_memory_payload persona_text")

    old_status = '''            "memory_health": self.memory_health(),
            "active_session": {'''
    new_status = '''            "memory_health": self.memory_health(),
            "identity_anchor": self.get_user_identity(),
            "active_session": {'''
    source = replace_once(source, old_status, new_status, "get_status identity_anchor")

    AICORE_FILE.write_text(source, encoding="utf-8")
    py_compile.compile(str(AICORE_FILE), doraise=True)
    return bak


def write_test_script() -> Path:
    path = Path("tools/test_identity_anchor.py")
    bak = backup(path) if path.exists() else path.with_name(path.name + ".bak.created")
    path.write_text(TEST_SCRIPT, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)
    return bak


def main() -> None:
    bak1 = patch_aicore()
    bak2 = write_test_script()

    print("✅ identity anchor patch 完成并通过语法检查")
    print(f"backup_aicore : {bak1}")
    print(f"backup_test   : {bak2}")
    print("下一步运行：")
    print("python3 tools/test_identity_anchor.py")
    print("python - <<'PY'")
    print("from core.aicore.aicore import get_aicore_instance")
    print("aicore = get_aicore_instance()")
    print("print(aicore.get_status())")
    print("PY")


if __name__ == "__main__":
    main()
