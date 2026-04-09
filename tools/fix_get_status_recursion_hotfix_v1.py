#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import py_compile
import shutil
from datetime import datetime
from pathlib import Path

TARGET = Path("core/aicore/extensible_aicore.py")

HOTFIX_BLOCK = r'''
# === SANHUA_STATUS_RECURSION_HOTFIX_V1_BEGIN ===
from pathlib import Path as _sanhua_status_Path
import json as _sanhua_status_json


def _sanhua_status_project_root():
    return _sanhua_status_Path(__file__).resolve().parents[2]


def _sanhua_status_safe_runtime_truth(self):
    base_url = "http://127.0.0.1:8080"
    try:
        active = self.config.get_active_backends()
        if active:
            base_url = str(active[0].base_url or base_url).rstrip("/")
    except Exception:
        pass

    if base_url.endswith("/v1"):
        models_url = base_url + "/models"
        truth_base = base_url[:-3]
    else:
        models_url = base_url + "/v1/models"
        truth_base = base_url

    try:
        r = requests.get(models_url, timeout=3)
        r.raise_for_status()
        data = r.json()

        models = []

        if isinstance(data.get("models"), list):
            for item in data["models"]:
                if isinstance(item, dict):
                    models.append(str(item.get("model") or item.get("name") or item.get("id") or "").strip())

        if isinstance(data.get("data"), list):
            for item in data["data"]:
                if isinstance(item, dict):
                    models.append(str(item.get("id") or item.get("model") or item.get("name") or "").strip())

        models = [m for m in models if m]
        runtime_model = models[0] if models else ""

        return {
            "ok": True,
            "base_url": truth_base,
            "runtime_model": runtime_model,
            "models": models,
            "error": "",
        }
    except Exception as e:
        return {
            "ok": False,
            "base_url": truth_base,
            "runtime_model": "",
            "models": [],
            "error": str(e),
        }


def _sanhua_status_safe_identity_anchor(self):
    # 1) 优先尝试已有属性/方法
    probe_methods = [
        "_get_identity_anchor",
        "_identity_anchor_status",
        "get_identity_anchor",
        "identity_anchor_status",
    ]
    for name in probe_methods:
        fn = getattr(self, name, None)
        if callable(fn):
            try:
                data = fn()
                if isinstance(data, dict):
                    return data
            except Exception:
                pass

    probe_attrs = [
        "identity_anchor",
        "_identity_anchor",
    ]
    for name in probe_attrs:
        val = getattr(self, name, None)
        if isinstance(val, dict):
            return val

    # 2) 回退 persona.json
    path = _sanhua_status_project_root() / "data" / "memory" / "persona.json"
    if not path.exists():
        return {}

    try:
        data = _sanhua_status_json.loads(path.read_text(encoding="utf-8"))
        profile = data.get("user_profile", {}) if isinstance(data, dict) else {}
        if not isinstance(profile, dict):
            return {}

        anchor = {
            "name": profile.get("name", ""),
            "aliases": profile.get("aliases", []),
            "preferred_style": profile.get("preferred_style", []),
            "project_focus": profile.get("project_focus", []),
            "stable_facts": profile.get("stable_facts", {}),
            "response_preferences": profile.get("response_preferences", {}),
            "notes": profile.get("notes", ""),
        }
        anchor["has_identity"] = bool(anchor.get("name"))
        return anchor
    except Exception:
        return {}


def _sanhua_status_safe_maintenance_runtime(self):
    probe_methods = [
        "_maintenance_runtime_status",
        "get_maintenance_runtime",
    ]
    for name in probe_methods:
        fn = getattr(self, name, None)
        if callable(fn):
            try:
                data = fn()
                if isinstance(data, dict):
                    return data
            except Exception:
                pass

    probe_attrs = [
        "_maintenance_runtime",
        "maintenance_runtime",
    ]
    for name in probe_attrs:
        val = getattr(self, name, None)
        if isinstance(val, dict):
            return val

    return {}


def _sanhua_status_safe_degraded_runtime(self):
    fn = getattr(self, "_degraded_runtime_status", None)
    if callable(fn):
        try:
            data = fn()
            if isinstance(data, dict):
                return data
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {}


def _sanhua_status_safe_get_status(self):
    active_session = {}
    try:
        if hasattr(self, "memory_manager") and self.memory_manager is not None:
            active_session = self.memory_manager.get_active_session() or {}
    except Exception:
        active_session = {}

    backend_status = {}
    try:
        if hasattr(self, "backend_manager") and self.backend_manager is not None:
            backend_status = self.backend_manager.get_backend_status() or {}
    except Exception as e:
        backend_status = {"error": str(e)}

    runtime_truth = _sanhua_status_safe_runtime_truth(self)

    status = {
        "version": getattr(self, "VERSION", ""),
        "uptime_s": int(time.time() - getattr(self, "start_time", time.time())),
        "backend_status": backend_status,
        "runtime_model_truth": runtime_truth,
        "health": {},
        "memory_health": {},
        "active_session": {
            "session_id": active_session.get("session_id", ""),
            "last_active_at": active_session.get("last_active_at", ""),
            "context_summary": active_session.get("context_summary", ""),
        },
    }

    try:
        if hasattr(self, "health_monitor") and self.health_monitor is not None:
            status["health"] = self.health_monitor.health_report()
    except Exception as e:
        status["health"] = {"ok": False, "error": str(e)}

    try:
        if hasattr(self, "memory_health") and callable(self.memory_health):
            status["memory_health"] = self.memory_health()
    except Exception as e:
        status["memory_health"] = {"ok": False, "error": str(e)}

    auto_every = getattr(self, "_auto_consolidate_every", None)
    if auto_every is not None:
        status["auto_consolidate_every"] = auto_every

    successful_store_turns = getattr(self, "_successful_store_turns", None)
    if successful_store_turns is not None:
        status["successful_store_turns"] = successful_store_turns

    identity_anchor = _sanhua_status_safe_identity_anchor(self)
    if identity_anchor:
        status["identity_anchor"] = identity_anchor

    maintenance_runtime = _sanhua_status_safe_maintenance_runtime(self)
    if maintenance_runtime:
        status["maintenance_runtime"] = maintenance_runtime

    degraded_runtime = _sanhua_status_safe_degraded_runtime(self)
    if degraded_runtime:
        status["degraded_memory_runtime"] = degraded_runtime

    return status


if "ExtensibleAICore" in globals():
    setattr(ExtensibleAICore, "get_status", _sanhua_status_safe_get_status)

# === SANHUA_STATUS_RECURSION_HOTFIX_V1_END ===
'''


def backup(path: Path) -> Path:
    bak = path.with_name(path.name + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(path, bak)
    return bak


def main() -> None:
    if not TARGET.exists():
        raise SystemExit(f"未找到目标文件: {TARGET}")

    source = TARGET.read_text(encoding="utf-8")
    bak = backup(TARGET)

    begin = "# === SANHUA_STATUS_RECURSION_HOTFIX_V1_BEGIN ==="
    end = "# === SANHUA_STATUS_RECURSION_HOTFIX_V1_END ==="

    if begin in source and end in source:
        s = source.index(begin)
        e = source.index(end) + len(end)
        source = source[:s].rstrip() + "\n\n" + HOTFIX_BLOCK.strip() + "\n"
    else:
        source = source.rstrip() + "\n\n" + HOTFIX_BLOCK.strip() + "\n"

    TARGET.write_text(source, encoding="utf-8")
    py_compile.compile(str(TARGET), doraise=True)

    print("✅ get_status recursion hotfix v1 完成并通过语法检查")
    print(f"backup: {bak}")
    print("下一步运行：")
    print("python3 tools/test_degraded_negative_memory_v2.py")
    print("python - <<'PY'")
    print("from core.aicore.aicore import get_aicore_instance")
    print("aicore = get_aicore_instance()")
    print("print(aicore.get_status().get('degraded_memory_runtime'))")
    print("PY")


if __name__ == "__main__":
    main()
