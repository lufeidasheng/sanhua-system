#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


INSERT_BEFORE = "        count_after = _list_count()\n"

INSERT_BLOCK = r'''
        # 5) fallback safe actions
        try:
            existing = None
            if hasattr(dispatcher, "get_action"):
                existing = dispatcher.get_action("sysmon.status")

            if existing is None and hasattr(dispatcher, "register_action"):
                import os
                import platform
                import shutil
                import time

                try:
                    import psutil  # type: ignore
                except Exception:
                    psutil = None

                def _fallback_sysmon_status(context=None, **kwargs):
                    data = {
                        "ok": True,
                        "source": "aicore_fallback",
                        "timestamp": int(time.time()),
                        "platform": platform.platform(),
                        "python": platform.python_version(),
                        "cwd": os.getcwd(),
                    }

                    try:
                        if psutil is not None:
                            vm = psutil.virtual_memory()
                            du = psutil.disk_usage("/")
                            cpu = psutil.cpu_percent(interval=0.1)
                            data.update({
                                "cpu_percent": cpu,
                                "memory_total": int(vm.total),
                                "memory_used": int(vm.used),
                                "memory_available": int(vm.available),
                                "memory_percent": float(vm.percent),
                                "disk_total": int(du.total),
                                "disk_used": int(du.used),
                                "disk_free": int(du.free),
                            })
                        else:
                            du = shutil.disk_usage("/")
                            data.update({
                                "cpu_percent": None,
                                "memory_total": None,
                                "memory_used": None,
                                "memory_available": None,
                                "memory_percent": None,
                                "disk_total": int(du.total),
                                "disk_used": int(du.used),
                                "disk_free": int(du.free),
                            })
                    except Exception as inner_e:
                        data["metrics_error"] = str(inner_e)

                    if context is not None:
                        data["context"] = context
                    if kwargs:
                        data["kwargs"] = kwargs

                    return data

                dispatcher.register_action("sysmon.status", _fallback_sysmon_status)
                details.append({
                    "step": "fallback.sysmon.status",
                    "ok": True,
                    "mode": "direct_register",
                })
            else:
                details.append({
                    "step": "fallback.sysmon.status",
                    "ok": True,
                    "mode": "already_exists",
                })
        except Exception as e:
            details.append({
                "step": "fallback.sysmon.status",
                "ok": False,
                "error": str(e),
            })

'''.rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser(description="给 AICore bootstrap 注入 fallback 安全动作")
    ap.add_argument("--root", required=True)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    target = root / "core" / "aicore" / "aicore.py"
    if not target.exists():
        print(f"[ERROR] not found: {target}")
        raise SystemExit(1)

    text = target.read_text(encoding="utf-8", errors="ignore")

    if "fallback.sysmon.status" in text:
        print("[SKIP] fallback.sysmon.status 已存在，未重复注入")
        raise SystemExit(0)

    if INSERT_BEFORE not in text:
        print("[ERROR] 未找到注入锚点")
        raise SystemExit(1)

    text = text.replace(INSERT_BEFORE, INSERT_BLOCK + INSERT_BEFORE, 1)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = root / "audit_output" / "fix_backups" / ts / "core" / "aicore"
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup_dir / "aicore.py")

    target.write_text(text, encoding="utf-8")

    print("=" * 72)
    print("aicore fallback safe actions 补丁完成")
    print("=" * 72)
    print(f"[PATCHED] {target}")
    print(f"[BACKUP ] {backup_dir / 'aicore.py'}")
    print("=" * 72)


if __name__ == "__main__":
    main()
