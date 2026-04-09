#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="GUI 运行态启动测试")
    ap.add_argument("--root", required=True, help="项目根目录")
    ap.add_argument("--timeout", type=int, default=15, help="启动观察秒数")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    gui_main = root / "entry" / "gui_entry" / "gui_main.py"
    if not gui_main.exists():
        print(f"[ERROR] gui_main 不存在: {gui_main}")
        return 2

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("SANHUA_DISABLE_AUDIO_CAPTURE_PROCESS", "1")
    env.setdefault("SANHUA_GUI_TEST_MODE", "1")

    cmd = [sys.executable, str(gui_main)]

    started_at = time.time()
    proc = subprocess.Popen(
        cmd,
        cwd=str(root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )

    output = ""
    timed_out = False
    exit_code = None

    try:
        output, _ = proc.communicate(timeout=args.timeout)
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            proc.send_signal(signal.SIGTERM)
            output, _ = proc.communicate(timeout=5)
        except Exception:
            proc.kill()
            output, _ = proc.communicate()
        exit_code = proc.returncode

    elapsed = round(time.time() - started_at, 2)

    lines = output.splitlines()

    def contains(text: str) -> bool:
        return text in output

    gui_started = contains("启动三花聚顶 GUI") or contains("GUI - 真实环境")
    alias_zero = contains("aliases loaded = 0") or contains("aliases 未加载")
    alias_force_loaded = contains("aliases force loaded =") or contains("aliases loaded =")
    no_base_module_error = contains("未找到BaseModule子类")
    audio_pickle_error = contains("cannot pickle '_thread._local' object")
    traceback_seen = contains("Traceback (most recent call last):")
    libnotify_warn = contains("libnotify 不可用")
    glib_warn = contains("GLib-GIRepository-WARNING")
    actions_registered = contains("actions registered into ACTION_MANAGER")
    llm_ready = contains("LLM 就绪") or contains("llamacpp")

    # 判定逻辑
    hard_fail_reasons = []
    if not gui_started:
        hard_fail_reasons.append("未检测到 GUI 启动标记")
    if no_base_module_error:
        hard_fail_reasons.append("仍存在 BaseModule 子类缺失错误")
    if audio_pickle_error:
        hard_fail_reasons.append("audio_capture 仍触发 macOS spawn pickle 崩溃")
    if alias_zero and not alias_force_loaded:
        hard_fail_reasons.append("GUI aliases 仍未成功加载")

    # traceback 不是一票否决，要结合关键错误
    if traceback_seen and (no_base_module_error or audio_pickle_error):
        hard_fail_reasons.append("检测到 GUI 关键 traceback")

    if hard_fail_reasons:
        overall = "GUI_BOOT_FAIL"
    else:
        overall = "GUI_BOOT_OK" if (actions_registered or llm_ready or timed_out) else "GUI_BOOT_DEGRADED"

    out_log = root / "audit_output" / "test_gui_runtime_boot_v1.log"
    out_json = root / "audit_output" / "test_gui_runtime_boot_v1_report.json"
    out_log.parent.mkdir(parents=True, exist_ok=True)
    out_log.write_text(output, encoding="utf-8")
    out_json.write_text(
        json.dumps(
            {
                "ok": overall == "GUI_BOOT_OK",
                "overall": overall,
                "root": str(root),
                "cmd": cmd,
                "elapsed_sec": elapsed,
                "timeout_sec": args.timeout,
                "timed_out": timed_out,
                "exit_code": exit_code,
                "signals": {
                    "gui_started": gui_started,
                    "actions_registered": actions_registered,
                    "llm_ready": llm_ready,
                    "alias_zero": alias_zero,
                    "alias_force_loaded": alias_force_loaded,
                    "no_base_module_error": no_base_module_error,
                    "audio_pickle_error": audio_pickle_error,
                    "traceback_seen": traceback_seen,
                    "libnotify_warn": libnotify_warn,
                    "glib_warn": glib_warn,
                },
                "hard_fail_reasons": hard_fail_reasons,
                "log_path": str(out_log),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("=" * 100)
    print("TEST GUI RUNTIME BOOT V1")
    print("=" * 100)
    print(f"overall     : {overall}")
    print(f"elapsed_sec : {elapsed}")
    print(f"timeout_sec : {args.timeout}")
    print(f"timed_out   : {timed_out}")
    print(f"exit_code   : {exit_code}")
    print()

    print("[signals]")
    print(f"  gui_started         -> {gui_started}")
    print(f"  actions_registered  -> {actions_registered}")
    print(f"  llm_ready           -> {llm_ready}")
    print(f"  alias_zero          -> {alias_zero}")
    print(f"  alias_force_loaded  -> {alias_force_loaded}")
    print(f"  no_base_module_err  -> {no_base_module_error}")
    print(f"  audio_pickle_error  -> {audio_pickle_error}")
    print(f"  traceback_seen      -> {traceback_seen}")
    print(f"  libnotify_warn      -> {libnotify_warn}")
    print(f"  glib_warn           -> {glib_warn}")
    print()

    print("[hard_fail_reasons]")
    if hard_fail_reasons:
        for r in hard_fail_reasons:
            print(f"  - {r}")
    else:
        print("  (none)")

    print()
    print("[log tail]")
    tail = "\n".join(lines[-60:]) if lines else "(empty)"
    print(tail)
    print()
    print(f"log_report  : {out_log}")
    print(f"json_report : {out_json}")
    print("=" * 100)

    return 0 if overall == "GUI_BOOT_OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
