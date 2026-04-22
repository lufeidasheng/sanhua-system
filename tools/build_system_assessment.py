#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
三花聚顶系统｜系统总详细测评脚本（单文件首版）
------------------------------------------------
用途：
1. 扫描仓库静态结构
2. 检测模块、manifest、aliases、actions、events、语法错误、TODO/FIXME
3. 初步检测 GUI 越界 / 架构边界风险
4. 尝试探测本地运行态（llama.cpp / ollama / 环境变量）
5. 生成总报告、JSON、DOT 图、风险台账、规划输入

输出：
- reports/system_assessment/latest/system_report.json
- reports/system_assessment/latest/system_report.md
- reports/system_assessment/latest/module_graph.dot
- reports/system_assessment/latest/risk_register.json
- reports/system_assessment/latest/runtime_truth.json
- reports/system_assessment/latest/planning_input.md

建议运行：
    python3 tools/build_system_assessment.py --root /Users/lufei/Desktop/聚核助手2.0

若不传 --root，则默认使用当前工作目录。
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
import re
import socket
import sys
import traceback
import urllib.request
import urllib.error
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# -----------------------------
# 基础配置
# -----------------------------

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    "venv",
    ".venv",
    "env",
    ".env",
    "site-packages",
    "audit_output",
    "_chatgpt_project_bundle_v2",
    "__MACOSX",
}

PY_SUFFIX = ".py"
MANIFEST_NAME = "manifest.json"

ACTION_PATTERNS = [
    r"\bregister_action\s*\(",
    r"\bregister_actions\s*\(",
    r"\bACTION_MANAGER\b",
    r"\bdispatch_action\s*\(",
    r"\bcall_action\s*\(",
]

EVENT_PATTERNS = [
    r"\bpublish_event\s*\(",
    r"\bemit\s*\(",
    r"\bsubscribe\s*\(",
    r"\bon_event\s*\(",
    r"\bevent_bus\b",
]

ALIAS_TARGET_PATTERNS = [
    r"register_aliases\s*\(",
    r"aliases\.yaml",
    r"aliases\.darwin\.yaml",
]

TODO_PATTERNS = [
    r"\bTODO\b",
    r"\bFIXME\b",
    r"\bXXX\b",
    r"\bHACK\b",
    r"\bBUG\b",
]

GUI_BOUNDARY_IMPORT_HINTS = [
    "core.aicore",
    "core.memory_engine",
    "core.prompt_engine",
    "action_dispatcher",
    "dispatch_action",
    "call_action",
    "ACTION_MANAGER",
    "PromptMemoryBridge",
    "MemoryManager",
]

RUNTIME_PORTS = {
    "llamacpp": 8080,
    "ollama": 11434,
}

MAX_SAMPLE_ITEMS = 20

DEFAULT_ASSET_MAP_PATH = "reports/repo_assets/repo_asset_map.json"

MAINLINE_ALLOWED_SCOPES = {
    "runtime_code",
    "entrypoint",
    "module_runtime",
    "config",
    "control_plane",
    "test",
    "asset_governance_tool",
}


# -----------------------------
# 工具函数
# -----------------------------

def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def safe_read_text(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return ""


def safe_json_load(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(safe_read_text(path))
    except Exception:
        return None


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def relpath(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except Exception:
        return str(path)


def is_excluded(path: Path, root: Path) -> bool:
    parts = set(path.relative_to(root).parts)
    return any(part in DEFAULT_EXCLUDE_DIRS for part in parts)


def load_asset_map(root: Path, asset_map_path: Optional[str]) -> Dict[str, Any]:
    if not asset_map_path:
        return {}
    path = Path(asset_map_path)
    if not path.is_absolute():
        path = root / path
    data = safe_json_load(path)
    if not isinstance(data, dict):
        return {
            "_path": str(path),
            "_loaded": False,
            "_records": {},
        }
    records = {}
    for item in data.get("records", []) or []:
        if isinstance(item, dict) and item.get("path"):
            records[str(item["path"]).replace("\\", "/")] = item
    return {
        "_path": str(path),
        "_loaded": True,
        "_records": records,
    }


def asset_record_for(rel: str, asset_map: Dict[str, Any]) -> Dict[str, Any]:
    return (asset_map.get("_records") or {}).get(rel.replace("\\", "/"), {})


def is_mainline_asset(rel: str, asset_map: Dict[str, Any]) -> bool:
    rec = asset_record_for(rel, asset_map)
    return (
        rec.get("category") == "mainline"
        and rec.get("scope") in MAINLINE_ALLOWED_SCOPES
    )


def build_scan_scope(root: Path, scan_mode: str, asset_map: Dict[str, Any]) -> Dict[str, Any]:
    records = asset_map.get("_records") or {}
    category_counter = Counter()
    included = 0
    excluded = 0
    included_by_scope = Counter()
    excluded_by_category = Counter()

    if scan_mode == "mainline":
        for rec in records.values():
            category = rec.get("category") or "unknown"
            scope = rec.get("scope") or "unknown"
            category_counter[category] += 1
            if category == "mainline" and scope in MAINLINE_ALLOWED_SCOPES:
                included += 1
                included_by_scope[scope] += 1
            else:
                excluded += 1
                excluded_by_category[category] += 1
    else:
        for path in root.rglob("*"):
            if path.is_file() or path.is_dir():
                included += 1

    return {
        "scan_mode": scan_mode,
        "asset_map_path": asset_map.get("_path"),
        "asset_map_loaded": bool(asset_map.get("_loaded")),
        "allowed_scopes": sorted(MAINLINE_ALLOWED_SCOPES) if scan_mode == "mainline" else [],
        "included_asset_count": included,
        "excluded_asset_count": excluded,
        "included_by_scope": dict(included_by_scope),
        "excluded_by_category": dict(excluded_by_category),
        "asset_map_category_counts": dict(category_counter),
        "notes": (
            "mainline mode uses category=mainline plus allowed scopes from repo_asset_map.json"
            if scan_mode == "mainline"
            else "full mode is an explicit deep scan; it is not the default mainline assessment mode"
        ),
    }


def file_scope(rel: str, asset_map: Dict[str, Any], scan_mode: str) -> Dict[str, Any]:
    rec = asset_record_for(rel, asset_map)
    if rec:
        return {
            "category": rec.get("category", "unknown"),
            "scope": rec.get("scope", "unknown"),
            "matched_rule": rec.get("matched_rule", ""),
        }
    return {
        "category": "unknown" if scan_mode == "mainline" else "full_scan",
        "scope": "unknown" if scan_mode == "mainline" else "full_scan",
        "matched_rule": "missing_asset_map_record" if scan_mode == "mainline" else "full_scan",
    }


def risk_is_mainline_blocker(risk: Dict[str, Any]) -> bool:
    if risk.get("asset_scope") == "test":
        return False
    if risk.get("asset_category") != "mainline":
        return False
    return risk.get("severity") in {"high", "medium"}


def http_get_json(url: str, timeout: float = 1.5) -> Optional[Any]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "sanhua-assessment/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except Exception:
        return None


def port_open(host: str, port: int, timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def first_n(items: List[Any], n: int = MAX_SAMPLE_ITEMS) -> List[Any]:
    return items[:n]


def count_regex_hits(text: str, patterns: List[str]) -> int:
    total = 0
    for pat in patterns:
        total += len(re.findall(pat, text, flags=re.IGNORECASE | re.MULTILINE))
    return total


def find_regex_hits(text: str, patterns: List[str]) -> List[str]:
    hits: List[str] = []
    for pat in patterns:
        found = re.findall(pat, text, flags=re.IGNORECASE | re.MULTILINE)
        hits.extend(found)
    return hits


def guess_module_name_from_path(path: Path, root: Path) -> Optional[str]:
    rp = relpath(path, root).replace("\\", "/")
    if rp.startswith("modules/"):
        parts = rp.split("/")
        if len(parts) >= 2:
            return parts[1]
    return None


def flatten_import_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Import):
        if node.names:
            return node.names[0].name
    elif isinstance(node, ast.ImportFrom):
        if node.module:
            return node.module
    return None


# -----------------------------
# 代码解析
# -----------------------------

class FileAnalysisResult:
    def __init__(self, path: Path, rel: str):
        self.path = path
        self.rel = rel
        self.syntax_ok = True
        self.syntax_error: Optional[str] = None
        self.line_count = 0
        self.class_count = 0
        self.function_count = 0
        self.imports: List[str] = []
        self.action_hits = 0
        self.event_hits = 0
        self.todo_hits = 0
        self.gui_boundary_hits: List[str] = []
        self.module_name: Optional[str] = None
        self.file_size_bytes = 0
        self.asset_category = "unknown"
        self.asset_scope = "unknown"
        self.asset_matched_rule = ""


def analyze_python_file(path: Path, root: Path, asset_map: Optional[Dict[str, Any]] = None, scan_mode: str = "mainline") -> FileAnalysisResult:
    rel = relpath(path, root)
    result = FileAnalysisResult(path=path, rel=rel)
    result.module_name = guess_module_name_from_path(path, root)
    scope = file_scope(rel, asset_map or {}, scan_mode)
    result.asset_category = scope["category"]
    result.asset_scope = scope["scope"]
    result.asset_matched_rule = scope["matched_rule"]

    text = safe_read_text(path)
    result.file_size_bytes = path.stat().st_size if path.exists() else 0
    result.line_count = text.count("\n") + 1 if text else 0
    result.action_hits = count_regex_hits(text, ACTION_PATTERNS)
    result.event_hits = count_regex_hits(text, EVENT_PATTERNS)
    result.todo_hits = count_regex_hits(text, TODO_PATTERNS)

    if "gui" in rel.lower():
        for hint in GUI_BOUNDARY_IMPORT_HINTS:
            if hint in text:
                result.gui_boundary_hits.append(hint)

    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as e:
        result.syntax_ok = False
        result.syntax_error = f"{e.msg} (line {e.lineno}, col {e.offset})"
        return result
    except Exception as e:
        result.syntax_ok = False
        result.syntax_error = f"unknown parse error: {e}"
        return result

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            result.class_count += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result.function_count += 1
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            name = flatten_import_name(node)
            if name:
                result.imports.append(name)

    return result


# -----------------------------
# manifest / aliases / runtime
# -----------------------------

def scan_manifests(root: Path, scan_mode: str = "mainline", asset_map: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    manifests = []
    invalid_manifests = []
    module_dirs = []

    modules_root = root / "modules"
    if modules_root.exists() and modules_root.is_dir():
        for child in modules_root.iterdir():
            if child.is_dir():
                module_dirs.append(child.name)
                manifest_path = child / MANIFEST_NAME
                manifest_rel = relpath(manifest_path, root)
                if scan_mode == "mainline" and not is_mainline_asset(manifest_rel, asset_map or {}):
                    continue
                if manifest_path.exists():
                    data = safe_json_load(manifest_path)
                    if data is None:
                        invalid_manifests.append({
                            "path": manifest_rel,
                            "error": "invalid json",
                        })
                    else:
                        manifests.append({
                            "path": manifest_rel,
                            "module_dir": child.name,
                            "name": data.get("name"),
                            "entry_class": data.get("entry_class"),
                            "enabled": data.get("enabled"),
                            "status": data.get("status"),
                            "categories": data.get("categories", []),
                            "actions_count": len(data.get("actions", []) or []),
                            "events_count": len(data.get("events", []) or []),
                            "market_compatible": data.get("market_compatible"),
                        })
                else:
                    invalid_manifests.append({
                        "path": manifest_rel,
                        "error": "missing manifest.json",
                    })

    manifest_name_mismatches = []
    for item in manifests:
        if item["name"] and item["name"] != item["module_dir"]:
            manifest_name_mismatches.append({
                "path": item["path"],
                "module_dir": item["module_dir"],
                "manifest_name": item["name"],
            })

    return {
        "module_dirs": sorted(module_dirs),
        "module_count": len(module_dirs),
        "manifests": manifests,
        "manifest_count": len(manifests),
        "invalid_manifests": invalid_manifests,
        "manifest_name_mismatches": manifest_name_mismatches,
    }


def scan_aliases(root: Path) -> Dict[str, Any]:
    candidates = [
        root / "config" / "aliases.yaml",
        root / "config" / "aliases.darwin.yaml",
    ]
    results = []

    for path in candidates:
        if path.exists():
            text = safe_read_text(path)
            # 这里不强依赖 yaml 库，做轻量解析
            lines = [line.rstrip() for line in text.splitlines()]
            non_comment = [
                line for line in lines
                if line.strip() and not line.strip().startswith("#")
            ]
            results.append({
                "path": relpath(path, root),
                "exists": True,
                "line_count": len(lines),
                "non_comment_line_count": len(non_comment),
                "sample": first_n(non_comment, 12),
            })
        else:
            results.append({
                "path": relpath(path, root),
                "exists": False,
            })

    return {
        "candidates": results,
    }


def scan_runtime_truth(root: Path) -> Dict[str, Any]:
    env_keys = [
        "SANHUA_LLM_BACKEND",
        "SANHUA_ACTIVE_MODEL",
        "SANHUA_LLAMA_BASE_URL",
        "LLAMA_MODEL",
        "LLAMA_PORT",
        "LLAMA_SERVER_BIN",
    ]
    env_snapshot = {k: os.environ.get(k) for k in env_keys if os.environ.get(k)}

    runtime = {
        "timestamp": now_iso(),
        "env": env_snapshot,
        "ports": {},
        "llamacpp": {},
        "ollama": {},
        "guesses": {},
    }

    # 端口开放探测
    for name, port in RUNTIME_PORTS.items():
        runtime["ports"][name] = {
            "host": "127.0.0.1",
            "port": port,
            "open": port_open("127.0.0.1", port),
        }

    # llama.cpp 探测
    llama_models = http_get_json("http://127.0.0.1:8080/v1/models")
    if llama_models is not None:
        runtime["llamacpp"]["detected"] = True
        runtime["llamacpp"]["models_response"] = llama_models
    else:
        runtime["llamacpp"]["detected"] = False

    # Ollama 探测
    ollama_tags = http_get_json("http://127.0.0.1:11434/api/tags")
    if ollama_tags is not None:
        runtime["ollama"]["detected"] = True
        runtime["ollama"]["tags_response"] = ollama_tags
    else:
        runtime["ollama"]["detected"] = False

    # 基于环境变量的轻量猜测
    runtime["guesses"]["active_backend"] = (
        os.environ.get("SANHUA_LLM_BACKEND")
        or ("llamacpp_server" if runtime["llamacpp"].get("detected") else None)
        or ("ollama" if runtime["ollama"].get("detected") else None)
    )
    runtime["guesses"]["active_model"] = (
        os.environ.get("SANHUA_ACTIVE_MODEL")
        or os.environ.get("LLAMA_MODEL")
    )
    runtime["guesses"]["llama_base_url"] = os.environ.get("SANHUA_LLAMA_BASE_URL")

    return runtime


# -----------------------------
# 风险与规划输入
# -----------------------------

def enrich_risk(
    risk: Dict[str, Any],
    *,
    asset_category: str = "unknown",
    asset_scope: str = "unknown",
    matched_rule: str = "",
) -> Dict[str, Any]:
    risk["asset_category"] = asset_category
    risk["asset_scope"] = asset_scope
    risk["matched_rule"] = matched_rule
    risk["mainline_blocker"] = risk_is_mainline_blocker(risk)
    return risk


def build_risks(
    root: Path,
    py_results: List[FileAnalysisResult],
    manifest_result: Dict[str, Any],
    asset_map: Optional[Dict[str, Any]] = None,
    scan_mode: str = "mainline",
) -> List[Dict[str, Any]]:
    risks: List[Dict[str, Any]] = []

    syntax_errors = [r for r in py_results if not r.syntax_ok]
    for r in syntax_errors:
        risks.append(enrich_risk({
            "type": "syntax_error",
            "severity": "high",
            "path": r.rel,
            "detail": r.syntax_error,
            "recommendation": "优先修复语法错误，避免扫描与运行链路继续污染。",
        }, asset_category=r.asset_category, asset_scope=r.asset_scope, matched_rule=r.asset_matched_rule))

    for item in manifest_result.get("invalid_manifests", []):
        severity = "medium" if item["error"] == "missing manifest.json" else "high"
        scope = file_scope(item["path"], asset_map or {}, scan_mode)
        risks.append(enrich_risk({
            "type": "manifest_issue",
            "severity": severity,
            "path": item["path"],
            "detail": item["error"],
            "recommendation": "补齐或修复 manifest.json，确保模块治理可统一解析。",
        }, asset_category=scope["category"], asset_scope=scope["scope"], matched_rule=scope["matched_rule"]))

    for item in manifest_result.get("manifest_name_mismatches", []):
        scope = file_scope(item["path"], asset_map or {}, scan_mode)
        risks.append(enrich_risk({
            "type": "manifest_name_mismatch",
            "severity": "medium",
            "path": item["path"],
            "detail": f"module_dir={item['module_dir']}, manifest_name={item['manifest_name']}",
            "recommendation": "让 manifest.name 与模块目录名保持一致。",
        }, asset_category=scope["category"], asset_scope=scope["scope"], matched_rule=scope["matched_rule"]))

    for r in py_results:
        if r.file_size_bytes > 120_000 or r.line_count > 1500:
            risks.append(enrich_risk({
                "type": "oversized_file",
                "severity": "medium",
                "path": r.rel,
                "detail": f"lines={r.line_count}, size={r.file_size_bytes} bytes",
                "recommendation": "考虑拆分过大文件，降低耦合与维护风险。",
            }, asset_category=r.asset_category, asset_scope=r.asset_scope, matched_rule=r.asset_matched_rule))

    for r in py_results:
        if r.gui_boundary_hits:
            risks.append(enrich_risk({
                "type": "gui_boundary_leak",
                "severity": "medium",
                "path": r.rel,
                "detail": f"GUI file contains boundary-sensitive hints: {sorted(set(r.gui_boundary_hits))}",
                "recommendation": "检查 GUI 是否承担了不应承担的认知装配、真相源或动作总控职责。",
            }, asset_category=r.asset_category, asset_scope=r.asset_scope, matched_rule=r.asset_matched_rule))

    todo_heavy = sorted(
        [r for r in py_results if r.todo_hits >= 5],
        key=lambda x: x.todo_hits,
        reverse=True,
    )
    for r in first_n(todo_heavy, 12):
        risks.append(enrich_risk({
            "type": "todo_hotspot",
            "severity": "low",
            "path": r.rel,
            "detail": f"todo_hits={r.todo_hits}",
            "recommendation": "检查该文件是否已成为长期技术债热点。",
        }, asset_category=r.asset_category, asset_scope=r.asset_scope, matched_rule=r.asset_matched_rule))

    return risks


def infer_capabilities(
    py_results: List[FileAnalysisResult],
    manifest_result: Dict[str, Any],
    runtime_truth: Dict[str, Any],
) -> Dict[str, Any]:
    all_imports = [imp for r in py_results for imp in r.imports]
    import_text = "\n".join(all_imports)

    capabilities = {
        "has_modules_dir": manifest_result.get("module_count", 0) > 0,
        "has_memory_engine": "memory_engine" in import_text,
        "has_prompt_memory_bridge": "prompt_memory_bridge" in import_text or "PromptMemoryBridge" in import_text,
        "has_action_dispatcher": "action_dispatcher" in import_text or "ACTION_MANAGER" in import_text,
        "has_gui": any("gui" in r.rel.lower() for r in py_results),
        "has_aliases_config": any(item.get("exists") for item in runtime_safe_alias_candidates(py_results, manifest_result)),
        "has_runtime_backend_signal": bool(runtime_truth.get("guesses", {}).get("active_backend")),
        "has_llamacpp_signal": bool(runtime_truth.get("llamacpp", {}).get("detected")),
        "has_ollama_signal": bool(runtime_truth.get("ollama", {}).get("detected")),
    }
    return capabilities


def runtime_safe_alias_candidates(py_results: List[FileAnalysisResult], manifest_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    # 只是为了 infer_capabilities 复用，不做复杂操作
    return [{"exists": True}] if any(r.action_hits > 0 for r in py_results) else []


def build_planning_input(
    report_json: Dict[str, Any],
    risks: List[Dict[str, Any]],
) -> str:
    summary = report_json["summary"]
    scan_scope = report_json.get("scan_scope", {})
    runtime = report_json["runtime_truth"]
    capabilities = report_json["capabilities"]

    high_risks = [r for r in risks if r["severity"] == "high"]
    medium_risks = [r for r in risks if r["severity"] == "medium"]

    lines: List[str] = []
    lines.append("# 三花聚顶系统｜功能规划输入摘要")
    lines.append("")
    lines.append(f"- 生成时间：{now_iso()}")
    lines.append(f"- scan_mode：{report_json.get('scan_mode')}")
    lines.append(f"- asset_map_path：{report_json.get('asset_map_path')}")
    lines.append(f"- 纳入资产数：{scan_scope.get('included_asset_count')}")
    lines.append(f"- 排除资产数：{scan_scope.get('excluded_asset_count')}")
    lines.append(f"- Python 文件数：{summary['python_file_count']}")
    lines.append(f"- 类总数：{summary['class_count']}")
    lines.append(f"- 函数总数：{summary['function_count']}")
    lines.append(f"- 模块目录数：{summary['module_count']}")
    lines.append(f"- manifest 数：{summary['manifest_count']}")
    lines.append(f"- 语法错误数：{summary['syntax_error_count']}")
    lines.append(f"- 风险项数：{summary['risk_count']}")
    lines.append(f"- 主链 blocker 数：{summary.get('mainline_blocker_count')}")
    lines.append("")

    lines.append("## 一、当前可确认能力")
    lines.append("")
    if capabilities["has_modules_dir"]:
        lines.append("- 已存在模块化目录结构，可作为模块治理基础。")
    if capabilities["has_action_dispatcher"]:
        lines.append("- 已存在动作调度相关能力痕迹，可继续统一 dispatch/call 口径。")
    if capabilities["has_memory_engine"]:
        lines.append("- 已存在记忆引擎相关能力痕迹，可继续推进记忆分层与回写闭环。")
    if capabilities["has_prompt_memory_bridge"]:
        lines.append("- 已存在 PromptMemoryBridge 相关痕迹，可继续升级为上下文装配桥。")
    if capabilities["has_gui"]:
        lines.append("- 已存在 GUI 侧入口与界面能力，可继续收口其职责边界。")
    if capabilities["has_llamacpp_signal"] or capabilities["has_ollama_signal"]:
        lines.append("- 已探测到本地模型后端运行信号，可继续建设运行态真相注入。")
    if not any(capabilities.values()):
        lines.append("- 当前可确认能力较少，需要补充更强的运行态采样与仓库语义扫描。")
    lines.append("")

    lines.append("## 二、当前主要短板")
    lines.append("")
    if summary["syntax_error_count"] > 0:
        lines.append("- 仓库仍存在语法错误，说明基础可运行性与扫描可信度需优先补强。")
    if high_risks:
        lines.append("- 存在高风险项，当前不宜盲目新增复杂功能，应先稳底座。")
    if medium_risks:
        lines.append("- 存在中风险项，涉及 GUI 边界、manifest 规范或过大文件等结构问题。")
    lines.append("- 当前测评仍以静态扫描为主，运行态真相仍需更深层采集。")
    lines.append("")

    lines.append("## 三、建议优先方向（短期）")
    lines.append("")
    lines.append("1. 先修复语法错误与 manifest 基础问题，提升仓库真相可信度。")
    lines.append("2. 建立统一运行态真相快照输出（backend / model / modules / health）。")
    lines.append("3. 推进 GUI 边界收口，防止继续承担认知装配与真相职责。")
    lines.append("4. 建立上下文装配链（truth snapshot + memory retrieve + budget + template）。")
    lines.append("5. 建立动作结果结构化回写，形成认知闭环。")
    lines.append("")

    lines.append("## 四、不建议当前直接开工的方向")
    lines.append("")
    lines.append("- 在底座未稳前，直接大面积扩展家居 / NAS / 多端复杂接入。")
    lines.append("- 继续把功能规划与施工真相混在同一线程中长期讨论。")
    lines.append("- 指望项目记忆承担多工位实时协作总线。")
    lines.append("")

    lines.append("## 五、给头脑风暴项目的推荐提问方式")
    lines.append("")
    lines.append("请基于本评估输入，严格区分“当前已实现 / 建议短期实现 / 中期增强 / 长期设想”，")
    lines.append("围绕聚感、记忆、上下文编排、模型调度、动作闭环、GUI可视化、模块治理输出下一步功能规划报告。")
    lines.append("")

    lines.append("## 六、当前运行态猜测")
    lines.append("")
    lines.append(f"- active_backend: {runtime.get('guesses', {}).get('active_backend')}")
    lines.append(f"- active_model: {runtime.get('guesses', {}).get('active_model')}")
    lines.append(f"- llama_base_url: {runtime.get('guesses', {}).get('llama_base_url')}")
    lines.append(f"- llamacpp_detected: {runtime.get('llamacpp', {}).get('detected')}")
    lines.append(f"- ollama_detected: {runtime.get('ollama', {}).get('detected')}")
    lines.append("")

    return "\n".join(lines)


# -----------------------------
# 图谱 / 报告生成
# -----------------------------

def build_import_graph_dot(py_results: List[FileAnalysisResult]) -> str:
    lines = [
        "digraph sanhua_module_graph {",
        '  rankdir=LR;',
        '  graph [fontsize=10];',
        '  node [shape=box, fontsize=10];',
        '  edge [fontsize=9];',
    ]

    nodes: Set[str] = set()
    edges: Set[Tuple[str, str]] = set()

    for r in py_results:
        src = r.rel.replace("\\", "/")
        nodes.add(src)
        for imp in r.imports[:50]:
            # 只保留相对有意义的内部痕迹
            if imp.startswith(("core", "modules", "entry", "config", "tools")):
                dst = imp
                nodes.add(dst)
                edges.add((src, dst))

    for n in sorted(nodes):
        safe_n = n.replace('"', '\\"')
        lines.append(f'  "{safe_n}";')

    for src, dst in sorted(edges):
        safe_src = src.replace('"', '\\"')
        safe_dst = dst.replace('"', '\\"')
        lines.append(f'  "{safe_src}" -> "{safe_dst}";')

    lines.append("}")
    return "\n".join(lines)


def build_markdown_report(report: Dict[str, Any]) -> str:
    s = report["summary"]
    scan_scope = report.get("scan_scope", {})
    runtime = report["runtime_truth"]
    risks = report["risks"]
    top_imports = report["top_imports"]
    syntax_errors = report["syntax_errors"]
    gui_hotspots = report["gui_boundary_hotspots"]
    manifests = report["manifests"]

    md: List[str] = []
    md.append("# 三花聚顶系统｜系统总详细测评报告")
    md.append("")
    md.append(f"- 生成时间：{report['generated_at']}")
    md.append(f"- 仓库根目录：`{report['root']}`")
    md.append(f"- scan_mode：`{report.get('scan_mode')}`")
    md.append(f"- asset_map_path：`{report.get('asset_map_path')}`")
    md.append(f"- asset_map_loaded：`{scan_scope.get('asset_map_loaded')}`")
    md.append("")

    md.append("## 一、总览")
    md.append("")
    md.append(f"- 纳入资产数：**{scan_scope.get('included_asset_count')}**")
    md.append(f"- 排除资产数：**{scan_scope.get('excluded_asset_count')}**")
    md.append(f"- mainline blocker 数：**{s.get('mainline_blocker_count')}**")
    md.append(f"- Python 文件数：**{s['python_file_count']}**")
    md.append(f"- 类总数：**{s['class_count']}**")
    md.append(f"- 函数总数：**{s['function_count']}**")
    md.append(f"- import 边数：**{s['import_edge_count']}**")
    md.append(f"- action 痕迹数：**{s['action_hit_count']}**")
    md.append(f"- event 痕迹数：**{s['event_hit_count']}**")
    md.append(f"- TODO/FIXME 总数：**{s['todo_hit_count']}**")
    md.append(f"- 模块目录数：**{s['module_count']}**")
    md.append(f"- manifest 数：**{s['manifest_count']}**")
    md.append(f"- 语法错误数：**{s['syntax_error_count']}**")
    md.append(f"- 风险数：**{s['risk_count']}**")
    md.append("")

    md.append("## 二、运行态真相探测")
    md.append("")
    md.append(f"- 猜测 active_backend：`{runtime.get('guesses', {}).get('active_backend')}`")
    md.append(f"- 猜测 active_model：`{runtime.get('guesses', {}).get('active_model')}`")
    md.append(f"- llama_base_url：`{runtime.get('guesses', {}).get('llama_base_url')}`")
    md.append(f"- llama.cpp 探测：`{runtime.get('llamacpp', {}).get('detected')}`")
    md.append(f"- Ollama 探测：`{runtime.get('ollama', {}).get('detected')}`")
    md.append("")

    md.append("## 三、模块与 manifest 概况")
    md.append("")
    md.append(f"- modules/ 下模块目录数：**{manifests['module_count']}**")
    md.append(f"- 有效 manifest 数：**{manifests['manifest_count']}**")
    md.append(f"- manifest 异常数：**{len(manifests['invalid_manifests'])}**")
    md.append(f"- manifest.name 与目录名不一致数：**{len(manifests['manifest_name_mismatches'])}**")
    md.append("")
    if manifests["invalid_manifests"]:
        md.append("### manifest 异常样本")
        md.append("")
        for item in first_n(manifests["invalid_manifests"], 12):
            md.append(f"- `{item['path']}` → {item['error']}")
        md.append("")

    md.append("## 四、语法错误")
    md.append("")
    if syntax_errors:
        for item in syntax_errors:
            md.append(f"- `{item['path']}` → {item['error']}")
    else:
        md.append("- 未发现语法错误。")
    md.append("")

    md.append("## 五、GUI 边界热点")
    md.append("")
    if gui_hotspots:
        for item in gui_hotspots:
            md.append(
                f"- `{item['path']}` → hits={item['count']} / hints={item['hints']}"
            )
    else:
        md.append("- 未发现明显 GUI 越界热点。")
    md.append("")

    md.append("## 六、Top imports")
    md.append("")
    for name, cnt in top_imports[:20]:
        md.append(f"- `{name}` → {cnt}")
    md.append("")

    md.append("## 七、风险台账摘要")
    md.append("")
    severity_counter = Counter(r["severity"] for r in risks)
    for sev in ("high", "medium", "low"):
        md.append(f"- {sev}: {severity_counter.get(sev, 0)}")
    md.append("")

    for sev in ("high", "medium", "low"):
        sev_items = [r for r in risks if r["severity"] == sev]
        if sev_items:
            md.append(f"### {sev.upper()} 风险样本")
            md.append("")
            for item in first_n(sev_items, 10):
                md.append(
                    f"- `{item['path']}` | {item['type']} | scope={item.get('asset_scope')} | mainline_blocker={item.get('mainline_blocker')} | {item['detail']} | 建议：{item['recommendation']}"
                )
            md.append("")

    md.append("## 八、结论与建议")
    md.append("")
    md.append("### 当前结论")
    md.append("")
    md.append("- 该测评结果适合作为“头脑风暴项目”的统一输入基线，但**不能直接替代真实控制面**。")
    md.append("- 若语法错误、manifest 异常、GUI 边界泄漏较多，应先稳底座，再大规模扩功能。")
    md.append("- 若本地后端已被探测到，下一步应优先把运行态真相纳入普通聊天链。")
    md.append("")
    md.append("### 建议下一步")
    md.append("")
    md.append("1. 修复高优先级语法错误与 manifest 问题。")
    md.append("2. 产出统一运行态真相快照。")
    md.append("3. 推进上下文编排链：truth snapshot + memory retrieve + budget + template。")
    md.append("4. 将本报告投喂给“功能讨论与路线规划”项目，做下一步功能规划。")
    md.append("")

    return "\n".join(md)


# -----------------------------
# 主流程
# -----------------------------

def collect_python_files(root: Path, scan_mode: str = "mainline", asset_map: Optional[Dict[str, Any]] = None) -> List[Path]:
    files: List[Path] = []
    for path in root.rglob(f"*{PY_SUFFIX}"):
        if not path.is_file():
            continue
        if is_excluded(path, root):
            continue
        rel = relpath(path, root)
        if scan_mode == "mainline" and not is_mainline_asset(rel, asset_map or {}):
            continue
        files.append(path)
    return sorted(files)


def build_report(root: Path, scan_mode: str = "mainline", asset_map_path: Optional[str] = DEFAULT_ASSET_MAP_PATH) -> Dict[str, Any]:
    asset_map = load_asset_map(root, asset_map_path if scan_mode == "mainline" else asset_map_path)
    scan_scope = build_scan_scope(root, scan_mode, asset_map)
    py_files = collect_python_files(root, scan_mode, asset_map)
    py_results: List[FileAnalysisResult] = [
        analyze_python_file(p, root, asset_map, scan_mode)
        for p in py_files
    ]

    manifest_result = scan_manifests(root, scan_mode, asset_map)
    alias_result = scan_aliases(root)
    runtime_truth = scan_runtime_truth(root)

    total_classes = sum(r.class_count for r in py_results)
    total_funcs = sum(r.function_count for r in py_results)
    total_import_edges = sum(len(r.imports) for r in py_results)
    total_action_hits = sum(r.action_hits for r in py_results)
    total_event_hits = sum(r.event_hits for r in py_results)
    total_todo_hits = sum(r.todo_hits for r in py_results)

    syntax_errors = [
        {"path": r.rel, "error": r.syntax_error}
        for r in py_results if not r.syntax_ok
    ]

    import_counter = Counter()
    for r in py_results:
        import_counter.update(r.imports)

    gui_boundary_hotspots = []
    for r in py_results:
        if r.gui_boundary_hits:
            gui_boundary_hotspots.append({
                "path": r.rel,
                "count": len(r.gui_boundary_hits),
                "hints": sorted(set(r.gui_boundary_hits)),
            })

    risks = build_risks(root, py_results, manifest_result, asset_map, scan_mode)
    capabilities = infer_capabilities(py_results, manifest_result, runtime_truth)

    report = {
        "generated_at": now_iso(),
        "root": str(root),
        "scan_mode": scan_mode,
        "asset_map_path": scan_scope["asset_map_path"],
        "scan_scope": scan_scope,
        "assessment_policy": {
            "mainline_default": scan_mode == "mainline",
            "full_scan_notice": "full mode is explicit deep scan, not default mainline assessment",
            "runtime_truth_role": "runtime evidence only; not mixed into mainline static blockers",
            "test_scope_rule": "scope=test findings are governance evidence and do not directly count as runtime mainline blockers",
        },
        "summary": {
            "python_file_count": len(py_results),
            "class_count": total_classes,
            "function_count": total_funcs,
            "import_edge_count": total_import_edges,
            "action_hit_count": total_action_hits,
            "event_hit_count": total_event_hits,
            "todo_hit_count": total_todo_hits,
            "module_count": manifest_result["module_count"],
            "manifest_count": manifest_result["manifest_count"],
            "syntax_error_count": len(syntax_errors),
            "risk_count": len(risks),
            "mainline_blocker_count": sum(1 for r in risks if r.get("mainline_blocker")),
        },
        "capabilities": capabilities,
        "runtime_truth": runtime_truth,
        "aliases": alias_result,
        "manifests": manifest_result,
        "top_imports": import_counter.most_common(50),
        "syntax_errors": syntax_errors,
        "gui_boundary_hotspots": gui_boundary_hotspots,
        "risks": risks,
        "files": [
            {
                "path": r.rel,
                "line_count": r.line_count,
                "size_bytes": r.file_size_bytes,
                "class_count": r.class_count,
                "function_count": r.function_count,
                "import_count": len(r.imports),
                "action_hits": r.action_hits,
                "event_hits": r.event_hits,
                "todo_hits": r.todo_hits,
                "syntax_ok": r.syntax_ok,
                "syntax_error": r.syntax_error,
                "module_name": r.module_name,
                "asset_category": r.asset_category,
                "asset_scope": r.asset_scope,
                "asset_matched_rule": r.asset_matched_rule,
                "imports": r.imports,
            }
            for r in py_results
        ],
    }

    return report


def write_outputs(root: Path, report: Dict[str, Any]) -> Dict[str, str]:
    out_dir = root / "reports" / "system_assessment" / "latest"
    ensure_dir(out_dir)

    json_path = out_dir / "system_report.json"
    md_path = out_dir / "system_report.md"
    dot_path = out_dir / "module_graph.dot"
    risk_path = out_dir / "risk_register.json"
    runtime_path = out_dir / "runtime_truth.json"
    planning_path = out_dir / "planning_input.md"

    # dot 图只使用本次报告纳入的文件，避免 mainline 模式下二次全仓混扫。
    py_results_for_dot = []
    for item in report["files"]:
        dummy = FileAnalysisResult(path=Path(item["path"]), rel=item["path"])
        dummy.imports = list(item.get("imports") or [])
        dummy.rel = item["path"]
        py_results_for_dot.append(dummy)

    graph_dot = build_import_graph_dot(py_results_for_dot)
    markdown = build_markdown_report(report)
    planning_input = build_planning_input(report, report["risks"])

    write_json(json_path, report)
    write_text(md_path, markdown)
    write_text(dot_path, graph_dot)
    write_json(risk_path, report["risks"])
    write_json(runtime_path, report["runtime_truth"])
    write_text(planning_path, planning_input)

    return {
        "system_report_json": str(json_path),
        "system_report_md": str(md_path),
        "module_graph_dot": str(dot_path),
        "risk_register_json": str(risk_path),
        "runtime_truth_json": str(runtime_path),
        "planning_input_md": str(planning_path),
    }


def print_console_summary(report: Dict[str, Any], outputs: Dict[str, str]) -> None:
    s = report["summary"]
    scan_scope = report.get("scan_scope", {})
    print("✅ 三花聚顶系统测评完成")
    print(f"时间: {report['generated_at']}")
    print(f"仓库: {report['root']}")
    print(f"scan_mode: {report.get('scan_mode')}")
    print(f"asset_map: {report.get('asset_map_path')}")
    print("-" * 60)
    print(f"纳入资产数     : {scan_scope.get('included_asset_count')}")
    print(f"排除资产数     : {scan_scope.get('excluded_asset_count')}")
    print(f"Python 文件数   : {s['python_file_count']}")
    print(f"类总数         : {s['class_count']}")
    print(f"函数总数       : {s['function_count']}")
    print(f"模块目录数     : {s['module_count']}")
    print(f"manifest 数    : {s['manifest_count']}")
    print(f"语法错误数     : {s['syntax_error_count']}")
    print(f"风险项数       : {s['risk_count']}")
    print(f"主链 blocker 数 : {s.get('mainline_blocker_count')}")
    print("-" * 60)
    print("输出文件:")
    for k, v in outputs.items():
        print(f"- {k}: {v}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="三花聚顶系统｜系统总详细测评脚本（单文件首版）"
    )
    parser.add_argument(
        "--root",
        type=str,
        default=".",
        help="仓库根目录，默认当前目录",
    )
    parser.add_argument(
        "--scan-mode",
        choices=("mainline", "full"),
        default="mainline",
        help="扫描模式：mainline 默认使用资产白名单；full 为显式深扫模式",
    )
    parser.add_argument(
        "--asset-map",
        type=str,
        default=DEFAULT_ASSET_MAP_PATH,
        help=f"资产分类映射路径，默认 {DEFAULT_ASSET_MAP_PATH}",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).expanduser().resolve()

    if not root.exists() or not root.is_dir():
        print(f"❌ root 不存在或不是目录: {root}", file=sys.stderr)
        return 2

    try:
        report = build_report(root, scan_mode=args.scan_mode, asset_map_path=args.asset_map)
        outputs = write_outputs(root, report)
        print_console_summary(report, outputs)
        return 0
    except KeyboardInterrupt:
        print("⛔ 用户中断", file=sys.stderr)
        return 130
    except Exception as e:
        print("❌ 测评脚本执行失败", file=sys.stderr)
        print(f"错误: {e}", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
