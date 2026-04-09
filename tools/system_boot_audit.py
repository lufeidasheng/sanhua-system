#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import ast
import importlib
import json
import os
import platform
import sys
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# 数据结构
# ============================================================

@dataclass
class CheckResult:
    name: str
    ok: bool
    level: str = "info"   # info / warn / error
    summary: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModuleAudit:
    module: str
    module_dir: str
    exists_module_py: bool = False
    exists_manifest: bool = False
    exists_init: bool = False

    manifest_ok: bool = False
    manifest_entry: Optional[str] = None
    manifest_entry_class: Optional[str] = None
    manifest_error: Optional[str] = None

    class_count: int = 0
    base_module_classes: List[str] = field(default_factory=list)
    all_classes: List[str] = field(default_factory=list)
    has_register_actions: bool = False
    has_entry: bool = False

    classification: str = "unknown"
    issues: List[str] = field(default_factory=list)
    suggested_entry_class: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuditReport:
    ok: bool
    overall: str
    root: str
    platform: str
    action_count: int
    bootstrap_info: Dict[str, Any]
    capabilities: List[CheckResult]
    actions: List[CheckResult]
    smokes: List[CheckResult]
    aliases: List[CheckResult]
    modules: List[ModuleAudit]
    summary: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "overall": self.overall,
            "root": self.root,
            "platform": self.platform,
            "action_count": self.action_count,
            "bootstrap_info": self.bootstrap_info,
            "capabilities": [x.to_dict() for x in self.capabilities],
            "actions": [x.to_dict() for x in self.actions],
            "smokes": [x.to_dict() for x in self.smokes],
            "aliases": [x.to_dict() for x in self.aliases],
            "modules": [x.to_dict() for x in self.modules],
            "summary": self.summary,
        }


# ============================================================
# 通用工具
# ============================================================

def log(*args: Any, **kwargs: Any) -> None:
    print(*args, **kwargs)


def ensure_sys_path(root: Path) -> None:
    root_str = str(root.resolve())
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def safe_read_text(path: Path) -> str:
    if not path.exists():
        return ""
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return path.read_text(errors="ignore")


def safe_json_load(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not path.exists():
        return None, "file_not_found"
    try:
        data = json.loads(safe_read_text(path))
    except Exception as e:
        return None, str(e)

    if not isinstance(data, dict):
        return None, "json_root_not_dict"
    return data, None


def normalize_actions(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [str(k) for k in raw.keys()]
    if isinstance(raw, (list, tuple, set)):
        out: List[str] = []
        for item in raw:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                name = item.get("name") or item.get("action")
                if name:
                    out.append(str(name))
            else:
                out.append(str(item))
        return out
    return [str(raw)]


def extract_base_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts: List[str] = []
        cur: ast.AST = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    return ""


def camelize(name: str) -> str:
    parts = [p for p in name.replace("-", "_").split("_") if p]
    if not parts:
        return "Unknown"
    return "".join(p[:1].upper() + p[1:] for p in parts)


def discover_best_module_class_name(module_name: str, module_py: Path) -> str:
    fallback = f"{camelize(module_name)}Module"
    if not module_py.exists():
        return fallback

    text = safe_read_text(module_py)
    try:
        tree = ast.parse(text, filename=str(module_py))
    except Exception:
        return fallback

    found: List[Tuple[str, List[str]]] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = [extract_base_name(b) for b in node.bases]
            found.append((node.name, bases))

    for name, bases in found:
        if any(base.endswith("BaseModule") or base == "BaseModule" for base in bases):
            return name

    for name, _ in found:
        if name.endswith("Module"):
            return name

    if found:
        return found[0][0]

    return fallback


# ============================================================
# AICore / Dispatcher 桥接
# ============================================================

class RuntimeBridge:
    def __init__(self, root: Path, *, force_bootstrap: bool = True) -> None:
        self.root = root.resolve()
        ensure_sys_path(self.root)
        os.chdir(self.root)

        from core.aicore.aicore import get_aicore_instance  # noqa

        self.aicore = get_aicore_instance()
        self.bootstrap_info: Dict[str, Any] = {}

        if force_bootstrap and hasattr(self.aicore, "_bootstrap_action_registry"):
            try:
                self.bootstrap_info = self.aicore._bootstrap_action_registry(force=True) or {}
            except Exception as e:
                self.bootstrap_info = {"ok": False, "reason": f"bootstrap_exception: {e}"}

        self._ensure_memory_actions()

    def resolve_dispatcher(self) -> Any:
        resolver = getattr(self.aicore, "_resolve_dispatcher", None)
        if callable(resolver):
            try:
                return resolver()
            except Exception:
                return None

        for name in ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager"):
            try:
                obj = getattr(self.aicore, name, None)
                if obj is not None:
                    return obj
            except Exception:
                continue
        return None

    def list_actions(self) -> List[str]:
        dispatcher = self.resolve_dispatcher()
        if dispatcher is None:
            return []
        try:
            return sorted(set(normalize_actions(dispatcher.list_actions())))
        except Exception:
            return []

    def has_action(self, name: str) -> bool:
        dispatcher = self.resolve_dispatcher()
        if dispatcher is None:
            return False
        try:
            if hasattr(dispatcher, "get_action"):
                return dispatcher.get_action(name) is not None
        except Exception:
            pass
        try:
            return name in self.list_actions()
        except Exception:
            return False

    def _ensure_memory_actions(self) -> None:
        required = [
            "memory.health",
            "memory.snapshot",
            "memory.search",
            "memory.recall",
            "memory.add",
            "memory.append_chat",
            "memory.append_action",
        ]
        missing = [x for x in required if not self.has_action(x)]
        if not missing:
            return

        dispatcher = self.resolve_dispatcher()
        if dispatcher is None:
            return

        try:
            mod = importlib.import_module("tools.memory_actions_official")
        except Exception:
            return

        register_fn = getattr(mod, "register_actions", None)
        if not callable(register_fn):
            register_fn = getattr(mod, "register_memory_actions", None)

        if not callable(register_fn):
            return

        try:
            info = register_fn(dispatcher=dispatcher, aicore=self.aicore)
        except TypeError:
            try:
                info = register_fn(dispatcher)
            except Exception:
                info = {"ok": False, "reason": "memory_register_failed"}
        except Exception:
            info = {"ok": False, "reason": "memory_register_failed"}

        if not self.bootstrap_info:
            self.bootstrap_info = {"ok": True, "reason": "bootstrapped"}
        details = self.bootstrap_info.setdefault("details", [])
        details.append({
            "step": "memory_actions",
            **(info if isinstance(info, dict) else {"ok": True, "result": str(info)}),
        })

        try:
            self.bootstrap_info["count_after"] = len(self.list_actions())
        except Exception:
            pass

    def process_action(
        self,
        action_name: str,
        *,
        runtime_context: Optional[Dict[str, Any]] = None,
        user_query: str = "",
    ) -> Dict[str, Any]:
        runtime_context = runtime_context or {}
        text = f"1. 调用 {action_name} 执行动作"

        try:
            result = self.aicore.process_suggestion_chain(
                text,
                user_query=user_query or f"invoke {action_name}",
                runtime_context=runtime_context,
                dry_run=False,
            )
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "step": {
                    "status": "failed",
                    "action_name": action_name,
                    "reason": str(e),
                },
            }

        steps = ((result.get("execution") or {}).get("step_results") or [])
        step = steps[0] if steps else {}
        return {
            "ok": step.get("status") == "ok",
            "raw": result,
            "step": step,
        }


# ============================================================
# alias 检查
# ============================================================

def audit_aliases(root: Path) -> List[CheckResult]:
    checks: List[CheckResult] = []
    config_dir = root / "config"
    base = config_dir / "aliases.yaml"

    plat = sys.platform.lower()
    plat_name = "darwin" if "darwin" in plat else ("linux" if "linux" in plat else plat)
    plat_file = config_dir / f"aliases.{plat_name}.yaml"

    base_exists = base.exists()
    plat_exists = plat_file.exists()

    checks.append(CheckResult(
        name="aliases.base_file",
        ok=base_exists,
        level="info" if base_exists else "warn",
        summary=str(base),
        detail={"exists": base_exists},
    ))
    checks.append(CheckResult(
        name="aliases.platform_file",
        ok=plat_exists,
        level="info" if plat_exists else "warn",
        summary=str(plat_file),
        detail={"exists": plat_exists, "platform": plat_name},
    ))

    if base_exists:
        text = safe_read_text(base)
        checks.append(CheckResult(
            name="aliases.base_nonempty",
            ok=bool(text.strip()),
            level="info" if text.strip() else "warn",
            summary="base aliases non-empty" if text.strip() else "base aliases empty",
            detail={"chars": len(text)},
        ))

    if plat_exists:
        text = safe_read_text(plat_file)
        checks.append(CheckResult(
            name="aliases.platform_nonempty",
            ok=bool(text.strip()),
            level="info" if text.strip() else "warn",
            summary="platform aliases non-empty" if text.strip() else "platform aliases empty",
            detail={"chars": len(text)},
        ))

    return checks


# ============================================================
# 模块分析
# ============================================================

def analyze_single_module(module_dir: Path) -> ModuleAudit:
    module_name = module_dir.name
    module_py = module_dir / "module.py"
    manifest_json = module_dir / "manifest.json"
    init_py = module_dir / "__init__.py"

    audit = ModuleAudit(
        module=module_name,
        module_dir=str(module_dir),
        exists_module_py=module_py.exists(),
        exists_manifest=manifest_json.exists(),
        exists_init=init_py.exists(),
    )

    # manifest
    manifest_data, manifest_error = safe_json_load(manifest_json)
    if manifest_error is None and manifest_data is not None:
        audit.manifest_ok = True
        audit.manifest_entry = manifest_data.get("entry")
        audit.manifest_entry_class = manifest_data.get("entry_class")
    else:
        audit.manifest_error = manifest_error

    # module.py AST
    if module_py.exists():
        text = safe_read_text(module_py)
        try:
            tree = ast.parse(text, filename=str(module_py))
        except Exception as e:
            audit.issues.append(f"module_py_parse_error: {e}")
            tree = None

        if tree is not None:
            classes: List[str] = []
            base_classes: List[str] = []

            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    classes.append(node.name)
                    bases = [extract_base_name(b) for b in node.bases]
                    if any(base.endswith("BaseModule") or base == "BaseModule" for base in bases):
                        base_classes.append(node.name)

                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name == "register_actions":
                        audit.has_register_actions = True
                    if node.name == "entry":
                        audit.has_entry = True

            audit.class_count = len(classes)
            audit.all_classes = classes
            audit.base_module_classes = base_classes

    # suggested entry class
    best_class = discover_best_module_class_name(module_name, module_py)
    audit.suggested_entry_class = f"modules.{module_name}.module.{best_class}"

    # classification
    if len(audit.base_module_classes) == 1:
        audit.classification = "official_module"
    elif len(audit.base_module_classes) > 1:
        audit.classification = "ambiguous_multiple_basemodule"
        audit.issues.append("multiple_basemodule_found")
    elif audit.has_register_actions:
        audit.classification = "legacy_action_module"
        audit.issues.append("no_BaseModule_subclass_but_register_actions_exists")
    elif audit.exists_module_py:
        audit.classification = "broken_module_shape"
        audit.issues.append("module_py_exists_but_no_BaseModule_and_no_register_actions")
    else:
        audit.classification = "missing_module_py"
        audit.issues.append("module_py_missing")

    # manifest consistency
    if not audit.exists_manifest:
        audit.issues.append("manifest_missing")
    else:
        if audit.manifest_entry != "module.py":
            audit.issues.append(f"manifest_entry_not_module_py: {audit.manifest_entry}")
        if audit.manifest_entry_class != audit.suggested_entry_class:
            audit.issues.append(
                f"manifest_entry_class_mismatch: current={audit.manifest_entry_class} "
                f"suggested={audit.suggested_entry_class}"
            )

    # __init__.py consistency
    if not audit.exists_init:
        audit.issues.append("__init__.py_missing")
    else:
        init_text = safe_read_text(init_py)
        if "from .module import" in init_text:
            audit.issues.append("__init__ strict import bridge")
        if "_import_module" in init_text and "__getattr__" in init_text:
            pass

    return audit


def audit_modules(root: Path) -> List[ModuleAudit]:
    modules_dir = root / "modules"
    if not modules_dir.exists():
        return []

    results: List[ModuleAudit] = []
    for child in sorted(modules_dir.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        if child.name.startswith(".") or child.name == "__pycache__":
            continue
        if (child / "module.py").exists() or (child / "manifest.json").exists():
            results.append(analyze_single_module(child))
    return results


# ============================================================
# 检查集合
# ============================================================

def audit_capabilities(bridge: RuntimeBridge) -> List[CheckResult]:
    a = bridge.aicore
    names = [
        "memory_manager",
        "prompt_memory_bridge",
        "process_suggestion_chain",
        "safe_apply_change_set",
        "evolve_file_replace",
    ]
    out: List[CheckResult] = []
    for name in names:
        exists = hasattr(a, name)
        out.append(CheckResult(
            name=name,
            ok=exists,
            level="info" if exists else "error",
            summary=f"hasattr({name})={exists}",
        ))
    return out


def audit_actions(bridge: RuntimeBridge) -> List[CheckResult]:
    required = [
        "ai.ask",
        "sysmon.status",
        "system.status",
        "code_reader.read_file",
        "code_reviewer.review_text",
        "code_executor.syntax_check",
        "code_inserter.preview_replace_text",
        "memory.health",
        "memory.snapshot",
        "memory.search",
        "memory.recall",
    ]
    out: List[CheckResult] = []
    for name in required:
        exists = bridge.has_action(name)
        out.append(CheckResult(
            name=name,
            ok=exists,
            level="info" if exists else "error",
            summary=f"action_present={exists}",
        ))
    return out


def audit_smokes(bridge: RuntimeBridge, root: Path) -> List[CheckResult]:
    cfg_path = "config/global.yaml"
    smoke_plan = [
        ("sysmon.status", {}, "smoke_sysmon_status"),
        ("system.status", {}, "smoke_system_status"),
        ("code_reader.read_file", {"path": cfg_path, "max_chars": 1200}, "smoke_code_reader"),
        ("code_executor.syntax_check", {"text": "def demo():\n    return 1\n"}, "smoke_syntax_check"),
        ("code_inserter.preview_append_text", {"path": cfg_path, "text": "\n# audit preview only\n"}, "smoke_preview_append"),
        ("memory.health", {}, "smoke_memory_health"),
        ("memory.snapshot", {}, "smoke_memory_snapshot"),
        ("memory.search", {"query": "鹏", "limit": 5}, "smoke_memory_search"),
    ]

    out: List[CheckResult] = []
    for action_name, ctx, label in smoke_plan:
        res = bridge.process_action(action_name, runtime_context=ctx, user_query=label)
        step = res.get("step") or {}
        ok = bool(res.get("ok"))
        output = step.get("output") or {}

        out.append(CheckResult(
            name=action_name,
            ok=ok,
            level="info" if ok else "error",
            summary=(
                f"ok={ok} status={step.get('status')} "
                f"source={output.get('source')} view={output.get('view')} "
                f"reason={step.get('reason')}"
            ),
            detail={
                "status": step.get("status"),
                "reason": step.get("reason"),
                "source": output.get("source"),
                "view": output.get("view"),
            },
        ))
    return out


# ============================================================
# 汇总判定
# ============================================================

def decide_overall(
    capability_checks: List[CheckResult],
    action_checks: List[CheckResult],
    smoke_checks: List[CheckResult],
    module_audits: List[ModuleAudit],
) -> Tuple[bool, str, Dict[str, Any]]:
    critical_capabilities_ok = all(x.ok for x in capability_checks)
    critical_actions_ok = all(x.ok for x in action_checks)
    critical_smoke_ok = all(x.ok for x in smoke_checks)

    official_count = sum(1 for m in module_audits if m.classification == "official_module")
    legacy_count = sum(1 for m in module_audits if m.classification == "legacy_action_module")
    ambiguous_count = sum(1 for m in module_audits if m.classification == "ambiguous_multiple_basemodule")
    broken_count = sum(
        1 for m in module_audits
        if m.classification in {"broken_module_shape", "missing_module_py"}
    )

    if critical_capabilities_ok and critical_actions_ok and critical_smoke_ok and broken_count == 0:
        overall = "BOOT_OK" if ambiguous_count == 0 else "BOOT_DEGRADED"
        ok = overall == "BOOT_OK"
    elif critical_capabilities_ok and critical_actions_ok:
        overall = "BOOT_DEGRADED"
        ok = False
    else:
        overall = "BOOT_FAIL"
        ok = False

    summary = {
        "critical_capabilities_ok": critical_capabilities_ok,
        "critical_actions_ok": critical_actions_ok,
        "critical_smoke_ok": critical_smoke_ok,
        "module_total": len(module_audits),
        "official_module_count": official_count,
        "legacy_action_module_count": legacy_count,
        "ambiguous_module_count": ambiguous_count,
        "broken_module_count": broken_count,
    }
    return ok, overall, summary


# ============================================================
# 打印
# ============================================================

def print_checks(title: str, checks: List[CheckResult]) -> None:
    log()
    log(f"[{title}]")
    for item in checks:
        icon = "✅" if item.ok else ("⚠️" if item.level == "warn" else "❌")
        log(f"  {icon} {item.name:<32} -> {item.summary}")


def print_module_summary(modules: List[ModuleAudit]) -> None:
    log()
    log("[module_classification]")
    for m in modules:
        extras = []
        if m.issues:
            extras.append("issues=" + str(len(m.issues)))
        if m.base_module_classes:
            extras.append("base=" + ",".join(m.base_module_classes))
        if m.has_register_actions:
            extras.append("register_actions=True")
        if m.manifest_entry_class:
            extras.append(f"entry_class={m.manifest_entry_class}")
        log(f"  - {m.module:<22} -> {m.classification} | " + " | ".join(extras))

    log()
    log("[module_issues]")
    for m in modules:
        if not m.issues:
            continue
        log(f"  {m.module}:")
        for issue in m.issues:
            log(f"    - {issue}")


# ============================================================
# 主流程
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="三花聚顶系统启动总审计脚本")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--json-out", default="", help="可选：输出 json 报告路径")
    parser.add_argument("--no-force-bootstrap", action="store_true", help="不强制 bootstrap")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        log(f"[ERROR] root not found: {root}")
        return 2

    ensure_sys_path(root)
    os.chdir(root)

    try:
        bridge = RuntimeBridge(root, force_bootstrap=not args.no_force_bootstrap)
    except Exception:
        log("[ERROR] RuntimeBridge init failed")
        log(traceback.format_exc())
        return 3

    capability_checks = audit_capabilities(bridge)
    action_checks = audit_actions(bridge)
    smoke_checks = audit_smokes(bridge, root)
    alias_checks = audit_aliases(root)
    module_audits = audit_modules(root)

    action_count = len(bridge.list_actions())
    ok, overall, summary = decide_overall(
        capability_checks,
        action_checks,
        smoke_checks,
        module_audits,
    )

    report = AuditReport(
        ok=ok,
        overall=overall,
        root=str(root),
        platform=f"{platform.system()} {platform.release()} ({sys.platform})",
        action_count=action_count,
        bootstrap_info=bridge.bootstrap_info or {},
        capabilities=capability_checks,
        actions=action_checks,
        smokes=smoke_checks,
        aliases=alias_checks,
        modules=module_audits,
        summary=summary,
    )

    log("=" * 100)
    log("SYSTEM BOOT AUDIT")
    log("=" * 100)
    log(f"overall      : {report.overall}")
    log(f"root         : {report.root}")
    log(f"platform     : {report.platform}")
    log(f"action_count : {report.action_count}")

    print_checks("capabilities", report.capabilities)
    print_checks("action_presence", report.actions)
    print_checks("smoke", report.smokes)
    print_checks("aliases", report.aliases)

    log()
    log("[bootstrap_info]")
    for k, v in (report.bootstrap_info or {}).items():
        if k == "details":
            log("  details:")
            for item in v:
                log(f"    - {item}")
        else:
            log(f"  {k:<14} -> {v}")

    print_module_summary(report.modules)

    log()
    log("[summary]")
    for k, v in report.summary.items():
        log(f"  {k:<28} -> {v}")

    if args.json_out:
        out_path = Path(args.json_out).resolve()
    else:
        out_path = root / "audit_output" / "system_boot_audit_report.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    log()
    log(f"json_report  : {out_path}")
    log("=" * 100)

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
