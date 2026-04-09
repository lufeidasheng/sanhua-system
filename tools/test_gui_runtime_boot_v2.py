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
from typing import Dict, List


def now_ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def safe_read(path: Path) -> str:
    if not path.exists():
        return ""
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return path.read_text(errors="ignore")


def safe_kill_process_group(proc: subprocess.Popen, grace_sec: float = 3.0) -> Dict[str, object]:
    """
    在 macOS / Linux 下优先杀整个进程组，避免 Qt / multiprocessing 子进程残留。
    """
    result: Dict[str, object] = {
        "terminated": False,
        "killed": False,
        "returncode": proc.returncode,
        "errors": [],
    }

    if proc.poll() is not None:
        result["returncode"] = proc.returncode
        return result

    try:
        pgid = os.getpgid(proc.pid)
    except Exception as e:
        result["errors"].append(f"getpgid_failed: {e}")
        pgid = None

    # 先 TERM
    try:
        if pgid is not None:
            os.killpg(pgid, signal.SIGTERM)
        else:
            proc.terminate()
        result["terminated"] = True
    except Exception as e:
        result["errors"].append(f"sigterm_failed: {e}")

    deadline = time.time() + grace_sec
    while time.time() < deadline:
        if proc.poll() is not None:
            result["returncode"] = proc.returncode
            return result
        time.sleep(0.1)

    # 再 KILL
    try:
        if pgid is not None:
            os.killpg(pgid, signal.SIGKILL)
        else:
            proc.kill()
        result["killed"] = True
    except Exception as e:
        result["errors"].append(f"sigkill_failed: {e}")

    deadline = time.time() + 2.0
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        time.sleep(0.1)

    result["returncode"] = proc.returncode
    return result


def collect_signals(output: str) -> Dict[str, bool]:
    def contains(*parts: str) -> bool:
        return any(p in output for p in parts)

    return {
        "gui_started": contains("启动三花聚顶 GUI", "GUI - 真实环境"),
        "security_manager_ready": contains("SecurityManager 初始化完成"),
        "actions_registered": contains("actions registered into ACTION_MANAGER", "actions registered"),
        "llm_ready": contains("LLM 就绪", "llamacpp"),
        "aliases_zero": contains("aliases loaded = 0", "aliases 未加载"),
        "aliases_force_loaded": contains("aliases force loaded =", "aliases loaded = "),
        "no_base_module_error": contains("未找到BaseModule子类"),
        "audio_pickle_error": contains("cannot pickle '_thread._local' object"),
        "traceback_seen": contains("Traceback (most recent call last):"),
        "libnotify_warn": contains("libnotify 不可用"),
        "glib_warn": contains("GLib-GIRepository-WARNING"),
        "qt_keyboard_noise": contains("IMKCFRunLoopWakeUpReliable", "TSM AdjustCapsLockLEDForKeyTransitionHandling"),
        "module_loaded_as_legacy": contains("module_loaded_as_legacy"),
        "multiple_basemodule_found": contains("multiple_basemodule_found"),
        "audio_capture_started": contains("audio_capture 模块启动中"),
        "audio_capture_setup_ok": contains("audio_capture模块setup完成", "audio_capture 模块设置完成"),
        "stt_started": contains("STT 子进程已启动"),
        "tts_broadcast": contains("[TTS] 已自动播报"),
    }


def classify(signals: Dict[str, bool], timed_out: bool) -> (str, List[str], List[str]):
    """
    输出 overall / hard_fail_reasons / warnings
    """
    hard_fail: List[str] = []
    warnings: List[str] = []

    if not signals["gui_started"]:
        hard_fail.append("未检测到 GUI 启动标记")

    if signals["no_base_module_error"]:
        hard_fail.append("仍存在 BaseModule 子类缺失错误")

    if signals["audio_pickle_error"]:
        hard_fail.append("audio_capture 仍触发 _thread._local pickle 崩溃")

    # aliases=0 只有在没有 force loaded 痕迹时才算硬问题
    if signals["aliases_zero"] and not signals["aliases_force_loaded"]:
        hard_fail.append("GUI aliases 仍未成功加载")

    if signals["module_loaded_as_legacy"]:
        warnings.append("日志中仍存在 module_loaded_as_legacy，说明 GUI 路径可能还在走旧兼容链")

    if signals["multiple_basemodule_found"]:
        warnings.append("日志中仍存在 multiple_basemodule_found，需继续清理模块管理器识别逻辑")

    if signals["glib_warn"]:
        warnings.append("desktop_notify / libnotify 在 macOS 下仍是降级状态，但通常不阻塞 GUI")

    if signals["qt_keyboard_noise"]:
        warnings.append("Qt 输入法噪音日志存在，但通常不影响功能")

    if hard_fail:
        return "GUI_BOOT_FAIL", hard_fail, warnings

    # GUI 程序超时不退出，本身反而常是“进入事件循环”的正向信号
    if timed_out and (signals["gui_started"] or signals["actions_registered"] or signals["llm_ready"]):
        return "GUI_BOOT_OK", hard_fail, warnings

    if signals["gui_started"] and (signals["actions_registered"] or signals["llm_ready"]):
        return "GUI_BOOT_OK", hard_fail, warnings

    return "GUI_BOOT_DEGRADED", hard_fail, warnings


def main() -> int:
    ap = argparse.ArgumentParser(description="GUI 运行态启动测试 v2（抗卡死版）")
    ap.add_argument("--root", required=True, help="项目根目录")
    ap.add_argument("--timeout", type=int, default=15, help="观察秒数")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    gui_main = root / "entry" / "gui_entry" / "gui_main.py"
    if not gui_main.exists():
        print(f"[ERROR] gui_main 不存在: {gui_main}")
        return 2

    audit_dir = root / "audit_output"
    audit_dir.mkdir(parents=True, exist_ok=True)

    log_path = audit_dir / "test_gui_runtime_boot_v2.log"
    report_path = audit_dir / "test_gui_runtime_boot_v2_report.json"

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("SANHUA_GUI_TEST_MODE", "1")
    env.setdefault("SANHUA_DISABLE_AUDIO_CAPTURE_PROCESS", "1")

    cmd = [sys.executable, str(gui_main)]

    started_at = time.time()
    with log_path.open("w", encoding="utf-8", errors="ignore") as logf:
        proc = subprocess.Popen(
            cmd,
            cwd=str(root),
            env=env,
            stdout=logf,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,  # 关键：让 killpg 生效
        )

        timed_out = False
        try:
            proc.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True

        kill_info = safe_kill_process_group(proc, grace_sec=3.0)

    elapsed = round(time.time() - started_at, 2)
    output = safe_read(log_path)
    signals = collect_signals(output)
    overall, hard_fail_reasons, warnings = classify(signals, timed_out)

    tail_lines = output.splitlines()[-80:]
    log_tail = "\n".join(tail_lines)

    report = {
        "ok": overall == "GUI_BOOT_OK",
        "overall": overall,
        "root": str(root),
        "cmd": cmd,
        "started_at": now_ts(),
        "elapsed_sec": elapsed,
        "timeout_sec": args.timeout,
        "timed_out": timed_out,
        "returncode": kill_info.get("returncode"),
        "kill_info": kill_info,
        "signals": signals,
        "hard_fail_reasons": hard_fail_reasons,
        "warnings": warnings,
        "log_path": str(log_path),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 100)
    print("TEST GUI RUNTIME BOOT V2")
    print("=" * 100)
    print(f"overall     : {overall}")
    print(f"elapsed_sec : {elapsed}")
    print(f"timeout_sec : {args.timeout}")
    print(f"timed_out   : {timed_out}")
    print(f"returncode  : {kill_info.get('returncode')}")
    print(f"log_path    : {log_path}")
    print(f"json_report : {report_path}")
    print()

    print("[signals]")
    for k, v in signals.items():
        print(f"  {k:<24} -> {v}")

    print()
    print("[hard_fail_reasons]")
    if hard_fail_reasons:
        for x in hard_fail_reasons:
            print(f"  - {x}")
    else:
        print("  (none)")

    print()
    print("[warnings]")
    if warnings:
        for x in warnings:
            print(f"  - {x}")
    else:
        print("  (none)")

    print()
    print("[log tail]")
    print(log_tail if log_tail else "(empty)")
    print("=" * 100)

    return 0 if overall == "GUI_BOOT_OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
