#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import py_compile
import re
import shutil
from datetime import datetime
from pathlib import Path


TARGET = Path("core/aicore/extensible_aicore.py")


REPLACEMENT = '''
    def _get_runtime_model_truth(self) -> Dict[str, Any]:
        base_url = (getattr(self.controller, "base_url", "") or "http://127.0.0.1:8080").rstrip("/")

        result: Dict[str, Any] = {
            "ok": False,
            "base_url": base_url,
            "runtime_model": "",
            "models": [],
            "error": "",
        }

        try:
            resp = requests.get(urljoin(base_url + "/", "v1/models"), timeout=5)
            resp.raise_for_status()
            data = resp.json() if resp.content else {}

            models: List[str] = []

            data_items = data.get("data", [])
            if isinstance(data_items, list):
                for item in data_items:
                    if not isinstance(item, dict):
                        continue
                    runtime_model = str(
                        item.get("id") or item.get("model") or item.get("name") or ""
                    ).strip()
                    if runtime_model:
                        models.append(runtime_model)

            if not models:
                model_items = data.get("models", [])
                if isinstance(model_items, list):
                    for item in model_items:
                        if not isinstance(item, dict):
                            continue
                        runtime_model = str(
                            item.get("model") or item.get("name") or item.get("id") or ""
                        ).strip()
                        if runtime_model:
                            models.append(runtime_model)

            models = list(dict.fromkeys(models))

            if models:
                result["ok"] = True
                result["runtime_model"] = models[0]
                result["models"] = models
            else:
                result["error"] = "no model returned from /v1/models"

        except Exception as e:
            result["error"] = str(e)

        return result

    def _augment_backend_status_with_runtime_truth(
        self,
        backend_status: Dict[str, Any],
        truth: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not isinstance(backend_status, dict):
            return backend_status

        truth = truth if isinstance(truth, dict) else self._get_runtime_model_truth()

        compact_truth = {
            "ok": truth.get("ok", False),
            "runtime_model": truth.get("runtime_model", ""),
            "error": truth.get("error", ""),
        }

        for backend_name, entry in list(backend_status.items()):
            if not isinstance(entry, dict):
                continue

            config = entry.get("config", {})
            if not isinstance(config, dict):
                config = {}

            config_model = str(config.get("model_name", "")).strip()
            runtime_model = str(truth.get("runtime_model", "")).strip()

            entry["config_model_name"] = config_model
            entry["resolved_runtime_model"] = runtime_model
            entry["model_name_mismatch"] = bool(config_model and runtime_model and config_model != runtime_model)
            entry["runtime_truth"] = compact_truth

        return backend_status

    def get_status(self) -> Dict[str, Any]:
        active_session = {}
        try:
            active_session = self.memory_manager.get_active_session()
        except Exception:
            pass

        truth = self._get_runtime_model_truth()
        backend_status = self.backend_manager.get_backend_status()
        backend_status = self._augment_backend_status_with_runtime_truth(backend_status, truth)

        return {
            "version": self.VERSION,
            "uptime_s": int(time.time() - self.start_time),
            "backend_status": backend_status,
            "runtime_model_truth": truth,
            "health": self.health_monitor.health_report(),
            "memory_health": self.memory_health(),
            "active_session": {
                "session_id": active_session.get("session_id", ""),
                "last_active_at": active_session.get("last_active_at", ""),
                "context_summary": active_session.get("context_summary", ""),
            },
            "auto_consolidate_every": self._auto_consolidate_every,
            "successful_store_turns": self._successful_store_turns,
        }
'''


def main() -> None:
    if not TARGET.exists():
        raise SystemExit(f"未找到文件: {TARGET}")

    source = TARGET.read_text(encoding="utf-8")
    backup = TARGET.with_name(TARGET.name + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(TARGET, backup)

    pattern = re.compile(
        r"(?s)    def _get_runtime_model_truth\(self\) -> Dict\[str, Any\]:\n.*?(?=    def debug_memory_prompt\()"
    )
    match = pattern.search(source)
    if not match:
        raise SystemExit("未匹配到 runtime truth / get_status 区块，补丁终止。")

    patched = source[:match.start()] + REPLACEMENT.strip("\n") + "\n\n" + source[match.end():]

    TARGET.write_text(patched, encoding="utf-8")
    py_compile.compile(str(TARGET), doraise=True)

    print("✅ status compact truth patch 完成并通过语法检查")
    print(f"backup: {backup}")


if __name__ == "__main__":
    main()
