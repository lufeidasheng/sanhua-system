#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import importlib
import traceback

MODULES = [
    "modules.system_monitor.module",
    "modules.system_control.module",
    "modules.code_reader.module",
    "modules.code_inserter.module",
    "modules.code_reviewer.module",
    "modules.logbook.module",
]


def main():
    for mod_name in MODULES:
        print("\n" + "=" * 88)
        print(mod_name)
        print("=" * 88)
        try:
            mod = importlib.import_module(mod_name)
            print("[OK] import success")

            if hasattr(mod, "register_actions"):
                fn = getattr(mod, "register_actions")
                print("[INFO] register_actions =", fn)
            else:
                print("[WARN] register_actions not found")

        except Exception:
            print("[ERROR] import failed")
            traceback.print_exc()


if __name__ == "__main__":
    main()
