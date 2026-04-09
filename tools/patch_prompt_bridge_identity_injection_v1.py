#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import py_compile
import shutil
from datetime import datetime
from pathlib import Path


BRIDGE_FILE = Path("core/prompt_engine/prompt_memory_bridge.py")


HELPER_BLOCK = r'''
from pathlib import Path
'''


METHOD_BLOCK = r'''
    # =========================
    # Identity anchor helpers
    # =========================

    def _persona_json_path(self) -> Path:
        return Path(__file__).resolve().parents[2] / "data" / "memory" / "persona.json"

    def _load_user_profile(self) -> Dict[str, Any]:
        path = self._persona_json_path()
        if not path.exists():
            return {}

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("读取 persona.json 失败: %s", e)
            return {}

        profile = data.get("user_profile", {})
        return profile if isinstance(profile, dict) else {}

    def _build_identity_anchor_block(self) -> str:
        profile = self._load_user_profile()
        if not profile:
            return ""

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

        if not name:
            return ""

        lines: List[str] = ["[身份锚点]"]
        lines.append(f"- 当前用户: {name}")

        alias_items = [str(x).strip() for x in aliases if str(x).strip()]
        if alias_items:
            lines.append("- 用户别名: " + ", ".join(alias_items))

        style_items = [str(x).strip() for x in preferred_style if str(x).strip()]
        if style_items:
            lines.append("- 回答风格偏好: " + ", ".join(style_items))

        project_items = [str(x).strip() for x in project_focus if str(x).strip()]
        if project_items:
            lines.append("- 当前项目焦点: " + ", ".join(project_items))

        tone = str(response_preferences.get("tone", "") or "").strip()
        structure = str(response_preferences.get("structure", "") or "").strip()
        verbosity = str(response_preferences.get("verbosity", "") or "").strip()

        if tone:
            lines.append(f"- 响应语气: {tone}")
        if structure:
            lines.append(f"- 响应结构: {structure}")
        if verbosity:
            lines.append(f"- 响应详细度: {verbosity}")

        identity_name = str(stable_facts.get("identity.name", "") or "").strip()
        primary_project = str(stable_facts.get("system.primary_project", "") or "").strip()
        response_pref = str(stable_facts.get("response.preference", "") or "").strip()

        if identity_name:
            lines.append(f"- 稳定事实.identity.name: {identity_name}")
        if primary_project:
            lines.append(f"- 稳定事实.system.primary_project: {primary_project}")
        if response_pref:
            lines.append(f"- 稳定事实.response.preference: {response_pref}")

        if notes:
            lines.append(f"- 备注: {notes}")

        return "\n".join(lines).strip()

    def _inject_identity_anchor(self, final_prompt: str) -> str:
        text = str(final_prompt or "").strip()
        if not text:
            return text

        identity_block = self._build_identity_anchor_block()
        if not identity_block:
            return text

        if "[身份锚点]" in text:
            return text

        insert_after_markers = [
            "[系统人格]",
            "[用户画像]",
        ]

        for marker in insert_after_markers:
            idx = text.find(marker)
            if idx != -1:
                marker_end = text.find("\n\n", idx)
                if marker_end != -1:
                    return text[:marker_end].rstrip() + "\n\n" + identity_block + "\n\n" + text[marker_end:].lstrip()

        return identity_block + "\n\n" + text
'''


TEST_SCRIPT = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from core.aicore.aicore import get_aicore_instance


def main() -> None:
    aicore = get_aicore_instance()

    payload = aicore.build_memory_payload(
        user_input="系统以后怎么记住我是鹏？",
        session_context={"source": "test_prompt_bridge_identity_injection"},
    )

    final_prompt = payload.get("final_prompt", "")

    print("=" * 72)
    print("identity_anchor_present")
    print("=" * 72)
    print("[身份锚点]" in final_prompt)

    print()
    print("=" * 72)
    print("final_prompt preview")
    print("=" * 72)
    print(final_prompt[:4000])


if __name__ == "__main__":
    main()
'''


def backup(path: Path) -> Path:
    bak = path.with_name(path.name + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(path, bak)
    return bak


def ensure_path_import(source: str) -> str:
    if "from pathlib import Path" in source:
        return source

    if "import json\n" in source:
        return source.replace("import json\n", "import json\nfrom pathlib import Path\n", 1)

    if "import logging\n" in source:
        return source.replace("import logging\n", "import logging\nfrom pathlib import Path\n", 1)

    return source


def insert_method_block(source: str) -> str:
    if "def _build_identity_anchor_block(self) -> str:" in source:
        return source

    anchor = "    def build_prompt("
    idx = source.find(anchor)
    if idx == -1:
        raise SystemExit("未找到 build_prompt 锚点，无法插入 identity helper。")

    return source[:idx] + METHOD_BLOCK.strip("\n") + "\n\n" + source[idx:]


def patch_build_prompt(source: str) -> str:
    if "final_prompt = self._inject_identity_anchor(final_prompt)" in source:
        return source

    candidates = [
        "        return final_prompt\n",
        "        return {\n",
    ]

    target = "        return final_prompt\n"
    if target in source:
        return source.replace(
            target,
            "        final_prompt = self._inject_identity_anchor(final_prompt)\n"
            "        return final_prompt\n",
            1,
        )

    payload_anchor = '            "final_prompt": final_prompt,\n'
    if payload_anchor in source:
        return source.replace(
            payload_anchor,
            '            "final_prompt": self._inject_identity_anchor(final_prompt),\n',
            1,
        )

    raise SystemExit("未找到 build_prompt 返回锚点。")


def patch_build_prompt_payload(source: str) -> str:
    old = '            "final_prompt": final_prompt,\n'
    new = '            "final_prompt": self._inject_identity_anchor(final_prompt),\n'
    if new in source:
        return source
    if old not in source:
        return source
    return source.replace(old, new, 1)


def write_test_script() -> Path:
    path = Path("tools/test_prompt_bridge_identity_injection.py")
    if path.exists():
        bak = backup(path)
    else:
        bak = path.with_name(path.name + ".bak.created")
    path.write_text(TEST_SCRIPT, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)
    return bak


def main() -> None:
    if not BRIDGE_FILE.exists():
        raise SystemExit(f"未找到文件: {BRIDGE_FILE}")

    source = BRIDGE_FILE.read_text(encoding="utf-8")
    bak = backup(BRIDGE_FILE)

    source = ensure_path_import(source)
    source = insert_method_block(source)
    source = patch_build_prompt(source)
    source = patch_build_prompt_payload(source)

    BRIDGE_FILE.write_text(source, encoding="utf-8")
    py_compile.compile(str(BRIDGE_FILE), doraise=True)

    bak_test = write_test_script()

    print("✅ prompt bridge identity injection patch 完成并通过语法检查")
    print(f"backup_bridge : {bak}")
    print(f"backup_test   : {bak_test}")
    print("下一步运行：")
    print("python3 tools/test_prompt_bridge_identity_injection.py")


if __name__ == "__main__":
    main()
