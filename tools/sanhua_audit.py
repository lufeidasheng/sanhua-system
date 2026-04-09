#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
三花聚顶系统结构审计脚本（只读版）

用途：
1. 扫描 memory / gui / model_engine / dispatcher 的重复资产
2. 校验 manifest.json 与代码结构一致性
3. 扫描旧路径 import 依赖
4. 生成 JSON / Markdown / Mermaid 报告

特点：
- 只读，不修改仓库
- 适合当前三花聚顶项目的结构收敛工作
- 标准库实现，无第三方依赖

建议运行：
    python3 tools/sanhua_audit.py --root "/Users/lufei/Desktop/聚核助手2.0"

或在项目根目录执行：
    python3 tools/sanhua_audit.py
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# =========================
# 配置区
# =========================

DEFAULT_IGNORED_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    ".pytest_cache",
    "__pycache__",
    ".mypy_cache",
    "node_modules",
    "venv",
    ".venv",
    "dependencies",
    "dist",
    "build",
    "logs",
    "runtime",
    "ollama_models",
    "ollama_data",
    "juyuan_models",
    "llama.cpp",
    "piper-master",
    "third_party",
    "rollback_snapshots",
    "certs",
    "models",
    "deps",
    "external",
    "recordings",
}

TRACKED_LEGACY_IMPORT_PREFIXES = [
    "core.aicore.memory",
    "core.aicore.model_engine2",
    "core.aicore.model_engine",
    "core.aicore.actions.action_dispatcher",
    "core.gui",
    "entry.gui_entry",
    "entry.gui_main",
    "core.core2_0.1.0",
    "模块.gui_entry",
]

CANONICAL_RULES = {
    "memory_manager": {
        "canonical_current": "core/memory_engine/memory_manager.py",
        "recommended_target": "core/memory_engine/",
        "description": "记忆引擎主入口应统一收敛到 core/memory_engine。",
    },
    "prompt_memory_bridge": {
        "canonical_current": "core/prompt_engine/prompt_memory_bridge.py",
        "recommended_target": "core/prompt_engine/",
        "description": "记忆注入桥应统一由 prompt_engine 管理。",
    },
    "memory_data_assets": {
        "canonical_current": "data/memory/",
        "recommended_target": "data/memory/",
        "description": "记忆持久化文件应统一收敛到 data/memory/ 目录。",
    },
    "gui_root": {
        "canonical_current": "gui/",
        "recommended_target": "gui/",
        "description": "GUI 真正主代码应只保留一套，统一在 gui/。",
    },
    "memory_dock": {
        "canonical_current": "gui/components/memory_dock.py",
        "recommended_target": "gui/components/memory_dock.py",
        "description": "MemoryDock 应属于 GUI 组件层，不应留在 core/gui/。",
    },
    "dispatcher": {
        "canonical_current": "core/core2_0/sanhuatongyu/action_dispatcher.py",
        "recommended_target": "core/action_dispatcher/action_dispatcher.py",
        "description": "当前推荐 sanhuatongyu 作为 Dispatcher 正式主实现，未来可外提到 core/action_dispatcher/。",
    },
    "model_engine": {
        "canonical_current": "core/aicore/model_engine.py",
        "recommended_target": "core/model_engine/model_engine.py",
        "description": "当前主 ModelEngine 多半仍在 aicore，下阶段建议外提到独立 core/model_engine/。",
    },
}


# =========================
# 数据结构
# =========================

@dataclass
class ManifestAudit:
    path: str
    scope: str
    module_dir: str
    name_in_manifest: Optional[str]
    entry: Optional[str]
    entry_exists: Optional[bool]
    entry_class: Optional[str]
    entry_class_module_file: Optional[str]
    entry_class_exists: Optional[bool]
    actions_count: int
    events_count: int
    dependencies_count: int
    issues: List[str] = field(default_factory=list)


@dataclass
class ImportHit:
    importer: str
    imported: str
    matched_prefix: str


@dataclass
class ConflictItem:
    path: str
    action: str
    note: str
    recommended_target: Optional[str] = None


@dataclass
class ConflictGroup:
    name: str
    description: str
    canonical_current: str
    recommended_target: str
    items: List[ConflictItem] = field(default_factory=list)


@dataclass
class ArchitectureIssue:
    severity: str
    title: str
    detail: str
    recommendation: str


# =========================
# 通用工具
# =========================

def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def to_rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def safe_read_text(path: Path) -> str:
    encodings = ("utf-8", "utf-8-sig", "gbk", "latin-1")
    for enc in encodings:
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def safe_json_load(path: Path) -> Any:
    text = safe_read_text(path)
    return json.loads(text)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, data: str) -> None:
    path.write_text(data, encoding="utf-8")


def markdown_escape(text: str) -> str:
    return text.replace("|", r"\|").replace("\n", "<br>")


def make_table(headers: List[str], rows: List[List[str]]) -> str:
    if not rows:
        return "_无数据_\n"
    out = []
    out.append("| " + " | ".join(headers) + " |")
    out.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        out.append("| " + " | ".join(markdown_escape(str(x)) for x in row) + " |")
    return "\n".join(out) + "\n"


# =========================
# 路径与遍历
# =========================

def should_ignore_dir_name(name: str, include_third_party: bool) -> bool:
    if name in {".", ".."}:
        return True
    if not include_third_party and name in DEFAULT_IGNORED_DIRS:
        return True
    return False


def iter_project_paths(root: Path, include_third_party: bool = False) -> Tuple[List[Path], List[Path]]:
    """
    返回：
    - directories
    - files
    """
    directories: List[Path] = []
    files: List[Path] = []

    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)

        # 原地裁剪
        dirnames[:] = [
            d for d in dirnames
            if not should_ignore_dir_name(d, include_third_party)
        ]

        for d in dirnames:
            directories.append(current / d)

        for f in filenames:
            files.append(current / f)

    return directories, files


def first_party_filter(path: Path, root: Path) -> bool:
    """
    第一方代码/资产过滤。
    """
    rel = to_rel(path, root)
    first_party_roots = (
        "core/",
        "gui/",
        "entry/",
        "modules/",
        "模块/",
        "data/",
        "tools/",
        "scripts/",
    )
    top_level_first_party_files = {
        "memory.json",
        "memory.pkl",
        "memory_data.json",
        "memory_retrieval.py",
        "trace_memory_summary_calls.py",
        "create_memory_module.py",
        "main_controller.py",
        "module_loader.py",
        "module_standardizer.py",
    }

    if rel in top_level_first_party_files:
        return True

    return rel.startswith(first_party_roots)


# =========================
# AST / import / class 检查
# =========================

def parse_python_ast(path: Path) -> Optional[ast.AST]:
    try:
        text = safe_read_text(path)
        return ast.parse(text, filename=str(path))
    except Exception:
        return None


def has_class_in_file(path: Path, class_name: str) -> bool:
    tree = parse_python_ast(path)
    if tree is None:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return True
    return False


def resolve_entry_class(entry_class: str, root: Path) -> Tuple[Optional[Path], Optional[bool]]:
    """
    entry_class 形如:
        modules.virtual_avatar.module.VirtualAvatarModule
    """
    if not entry_class or "." not in entry_class:
        return None, None

    parts = entry_class.split(".")
    if len(parts) < 2:
        return None, None

    class_name = parts[-1]
    module_path = Path(*parts[:-1])

    candidate_py = root / (str(module_path) + ".py")
    candidate_init = root / module_path / "__init__.py"

    if candidate_py.exists():
        return candidate_py, has_class_in_file(candidate_py, class_name)
    if candidate_init.exists():
        return candidate_init, has_class_in_file(candidate_init, class_name)

    return None, False


def scan_imports(py_files: List[Path], root: Path) -> List[ImportHit]:
    hits: List[ImportHit] = []

    for py_file in py_files:
        if not first_party_filter(py_file, root):
            continue

        tree = parse_python_ast(py_file)
        if tree is None:
            continue

        importer = to_rel(py_file, root)

        for node in ast.walk(tree):
            imported_modules: List[str] = []

            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.append(node.module)

            for imported in imported_modules:
                for prefix in TRACKED_LEGACY_IMPORT_PREFIXES:
                    if imported == prefix or imported.startswith(prefix + "."):
                        hits.append(
                            ImportHit(
                                importer=importer,
                                imported=imported,
                                matched_prefix=prefix,
                            )
                        )
                        break

    return hits


# =========================
# manifest 扫描
# =========================

def classify_manifest_scope(manifest_path: Path, root: Path) -> str:
    rel = to_rel(manifest_path, root)
    if rel.startswith("modules/"):
        return "modules"
    if rel.startswith("entry/"):
        return "entry"
    if rel.startswith("模块/"):
        return "legacy_cn_modules"
    if rel.startswith("core/"):
        return "core"
    return "other"


def resolve_entry_file(entry_value: Optional[str], manifest_dir: Path) -> Optional[bool]:
    if not entry_value:
        return None
    candidate = manifest_dir / entry_value
    return candidate.exists()


def scan_manifests(files: List[Path], root: Path) -> List[ManifestAudit]:
    results: List[ManifestAudit] = []

    manifest_files = [f for f in files if f.name == "manifest.json" and first_party_filter(f, root)]

    for mf in sorted(manifest_files):
        rel = to_rel(mf, root)
        scope = classify_manifest_scope(mf, root)
        module_dir = mf.parent.name

        issues: List[str] = []
        try:
            data = safe_json_load(mf)
            if not isinstance(data, dict):
                raise ValueError("manifest 顶层不是 object")
        except Exception as exc:
            results.append(
                ManifestAudit(
                    path=rel,
                    scope=scope,
                    module_dir=module_dir,
                    name_in_manifest=None,
                    entry=None,
                    entry_exists=None,
                    entry_class=None,
                    entry_class_module_file=None,
                    entry_class_exists=None,
                    actions_count=0,
                    events_count=0,
                    dependencies_count=0,
                    issues=[f"manifest 解析失败: {exc}"],
                )
            )
            continue

        name_in_manifest = data.get("name")
        entry = data.get("entry")
        entry_exists = resolve_entry_file(entry, mf.parent)
        entry_class = data.get("entry_class")
        entry_class_module_file, entry_class_exists = (None, None)

        if entry_class:
            mod_file, cls_exists = resolve_entry_class(entry_class, root)
            entry_class_module_file = to_rel(mod_file, root) if mod_file else None
            entry_class_exists = cls_exists

        actions = data.get("actions", [])
        events = data.get("events", [])
        dependencies = data.get("dependencies", [])

        if scope in {"modules", "legacy_cn_modules"} and name_in_manifest and name_in_manifest != module_dir:
            issues.append(f"name 与目录名不一致: manifest={name_in_manifest}, dir={module_dir}")

        if entry and entry_exists is False:
            issues.append(f"entry 文件不存在: {entry}")

        if entry_class and entry_class_exists is False:
            issues.append(f"entry_class 无法解析或类不存在: {entry_class}")

        if not entry_class:
            issues.append("缺少 entry_class")

        if not entry:
            issues.append("缺少 entry")

        if not isinstance(actions, list):
            issues.append("actions 不是 list")
            actions = []

        if not isinstance(events, list):
            issues.append("events 不是 list")
            events = []

        if not isinstance(dependencies, list):
            issues.append("dependencies 不是 list")
            dependencies = []

        results.append(
            ManifestAudit(
                path=rel,
                scope=scope,
                module_dir=module_dir,
                name_in_manifest=name_in_manifest,
                entry=entry,
                entry_exists=entry_exists,
                entry_class=entry_class,
                entry_class_module_file=entry_class_module_file,
                entry_class_exists=entry_class_exists,
                actions_count=len(actions),
                events_count=len(events),
                dependencies_count=len(dependencies),
                issues=issues,
            )
        )

    return results


# =========================
# 结构冲突分析
# =========================

def collect_matching(
    files: List[Path],
    directories: List[Path],
    root: Path,
) -> Dict[str, List[str]]:
    """
    收集与当前结构收敛任务强相关的资产。
    """
    matched: Dict[str, List[str]] = {
        "memory_manager_files": [],
        "prompt_memory_bridge_files": [],
        "memory_data_assets": [],
        "gui_roots": [],
        "gui_main_files": [],
        "memory_dock_files": [],
        "dispatcher_files": [],
        "model_engine_assets": [],
        "legacy_core_version_roots": [],
    }

    for d in directories:
        if not first_party_filter(d, root):
            continue
        rel = to_rel(d, root)

        if rel in {"gui", "core/gui", "entry/gui_entry", "模块/gui_entry"}:
            matched["gui_roots"].append(rel)

        if rel == "core/core2_0/1.0":
            matched["legacy_core_version_roots"].append(rel)

        if rel.endswith("/model_engine") or rel == "core/core2_0/sanhuatongyu/services/model_engine":
            matched["model_engine_assets"].append(rel)

    for f in files:
        if not first_party_filter(f, root):
            continue
        rel = to_rel(f, root)

        if f.name == "memory_manager.py":
            matched["memory_manager_files"].append(rel)

        if f.name == "prompt_memory_bridge.py":
            matched["prompt_memory_bridge_files"].append(rel)

        if f.name in {"memory.json", "memory.pkl", "memory_data.json", "memory_log.txt"}:
            matched["memory_data_assets"].append(rel)

        if f.name in {"main_gui.py", "gui_main.py"}:
            matched["gui_main_files"].append(rel)

        if f.name == "memory_dock.py":
            matched["memory_dock_files"].append(rel)

        if f.name == "action_dispatcher.py":
            matched["dispatcher_files"].append(rel)

        if "model_engine" in rel and (
            f.suffix == ".py" or f.name == "manifest.json"
        ):
            matched["model_engine_assets"].append(rel)

    for k in matched:
        matched[k] = sorted(set(matched[k]))

    return matched


def classify_memory_manager_item(path: str) -> ConflictItem:
    if path == "core/memory_engine/memory_manager.py":
        return ConflictItem(path, "KEEP_CANONICAL", "正式记忆引擎主入口", "core/memory_engine/")
    if path.startswith("core/aicore/memory/"):
        return ConflictItem(path, "DEPRECATE_LEGACY", "AICore 内嵌旧记忆实现，应逐步退役", "core/memory_engine/")
    return ConflictItem(path, "REVIEW", "需要人工确认是否仍被引用", "core/memory_engine/")


def classify_prompt_bridge_item(path: str) -> ConflictItem:
    if path == "core/prompt_engine/prompt_memory_bridge.py":
        return ConflictItem(path, "KEEP_CANONICAL", "正式 Prompt-Memory 桥", "core/prompt_engine/")
    return ConflictItem(path, "REVIEW", "非预期桥接实现，需确认", "core/prompt_engine/")


def classify_memory_data_item(path: str) -> ConflictItem:
    if path.startswith("data/"):
        return ConflictItem(path, "MIGRATE_TO_DATA_MEMORY_DIR", "保留为数据层资产，但建议迁到 data/memory/ 子目录", "data/memory/")
    if path.startswith("core/aicore/memory/") or path == "core/aicore/memory_data.json":
        return ConflictItem(path, "DEPRECATE_AICORE_SIDECAR", "AICore 内嵌记忆 sidecar，不应继续作为真相源", "data/memory/")
    if path in {"memory.json", "memory.pkl", "memory_data.json"}:
        return ConflictItem(path, "DEPRECATE_ROOT_SIDECAR", "根目录记忆 sidecar 易形成多真相源", "data/memory/")
    return ConflictItem(path, "REVIEW", "需要人工确认用途", "data/memory/")


def classify_gui_item(path: str) -> ConflictItem:
    if path == "gui" or path.startswith("gui/"):
        return ConflictItem(path, "KEEP_CANONICAL_GUI", "主 GUI 应统一保留在 gui/", "gui/")
    if path.startswith("entry/gui_entry/"):
        return ConflictItem(path, "KEEP_WRAPPER_OR_REVIEW", "入口包装可保留，但不应承载 GUI 主业务代码", "gui/")
    if path == "entry/gui_main.py":
        return ConflictItem(path, "DEPRECATE_ENTRY_DUPLICATE", "entry 层不应再持有 GUI 真代码", "gui/")
    if path == "core/gui" or path.startswith("core/gui/"):
        return ConflictItem(path, "DEPRECATE_CORE_GUI", "core/gui 与顶层 gui 重复，应退出主舞台", "gui/")
    if path.startswith("模块/gui_entry/") or path == "模块/gui_entry":
        return ConflictItem(path, "DEPRECATE_LEGACY_CN_GUI", "中文模块目录下的 GUI 入口属于历史残留", "gui/")
    return ConflictItem(path, "REVIEW", "需要人工确认用途", "gui/")


def classify_memory_dock_item(path: str) -> ConflictItem:
    if path == "gui/components/memory_dock.py":
        return ConflictItem(path, "KEEP_CANONICAL", "理想位置", "gui/components/memory_dock.py")
    if path == "core/gui/memory_dock.py":
        return ConflictItem(path, "MIGRATE_TO_GUI_COMPONENTS", "应迁到 gui/components/memory_dock.py", "gui/components/memory_dock.py")
    return ConflictItem(path, "REVIEW", "需确认是否重复实现", "gui/components/memory_dock.py")


def classify_dispatcher_item(path: str) -> ConflictItem:
    if path == "core/core2_0/sanhuatongyu/action_dispatcher.py":
        return ConflictItem(path, "KEEP_CURRENT_CANONICAL", "当前建议作为正式 Dispatcher 主实现", "core/action_dispatcher/action_dispatcher.py")
    if path == "core/aicore/actions/action_dispatcher.py":
        return ConflictItem(path, "DEPRECATE_OR_ADAPT", "AICore 内局部 Dispatcher，应降为适配层或退役", "core/action_dispatcher/action_dispatcher.py")
    if path == "core/core2_0/1.0/action_dispatcher.py":
        return ConflictItem(path, "DEPRECATE_LEGACY_VERSION", "旧版 1.0 Dispatcher，应停止参与主链", "core/action_dispatcher/action_dispatcher.py")
    return ConflictItem(path, "REVIEW", "需要人工确认用途", "core/action_dispatcher/action_dispatcher.py")


def classify_model_engine_item(path: str) -> ConflictItem:
    if path == "core/aicore/model_engine.py":
        return ConflictItem(path, "KEEP_CURRENT_PRIMARY", "当前主实现大概率仍在 AICore，后续建议外提", "core/model_engine/model_engine.py")
    if path == "core/aicore/model_engine2.py":
        return ConflictItem(path, "REVIEW_DUPLICATE", "疑似实验/副本实现，需要审查并收敛", "core/model_engine/model_engine.py")
    if path.startswith("modules/model_engine/"):
        return ConflictItem(path, "KEEP_MODULE_ADAPTER_OR_REVIEW", "模块层可保留适配封装，但不应取代 core service", "core/model_engine/")
    if path.startswith("modules/model_engine_actions/"):
        return ConflictItem(path, "KEEP_ACTION_ADAPTER_OR_REVIEW", "动作适配层可保留，但不应成为主实现", "core/model_engine/")
    if path == "core/core2_0/sanhuatongyu/services/model_engine":
        return ConflictItem(path, "REVIEW_SERVICE_IMPL", "存在服务实现痕迹，需确认与 AICore 版本的主从关系", "core/model_engine/")
    return ConflictItem(path, "REVIEW", "需要人工确认用途", "core/model_engine/")


def build_conflict_groups(matches: Dict[str, List[str]]) -> List[ConflictGroup]:
    groups: List[ConflictGroup] = []

    mg = ConflictGroup(
        name="memory_manager",
        description=CANONICAL_RULES["memory_manager"]["description"],
        canonical_current=CANONICAL_RULES["memory_manager"]["canonical_current"],
        recommended_target=CANONICAL_RULES["memory_manager"]["recommended_target"],
        items=[classify_memory_manager_item(p) for p in matches["memory_manager_files"]],
    )
    groups.append(mg)

    pmb = ConflictGroup(
        name="prompt_memory_bridge",
        description=CANONICAL_RULES["prompt_memory_bridge"]["description"],
        canonical_current=CANONICAL_RULES["prompt_memory_bridge"]["canonical_current"],
        recommended_target=CANONICAL_RULES["prompt_memory_bridge"]["recommended_target"],
        items=[classify_prompt_bridge_item(p) for p in matches["prompt_memory_bridge_files"]],
    )
    groups.append(pmb)

    mda = ConflictGroup(
        name="memory_data_assets",
        description=CANONICAL_RULES["memory_data_assets"]["description"],
        canonical_current=CANONICAL_RULES["memory_data_assets"]["canonical_current"],
        recommended_target=CANONICAL_RULES["memory_data_assets"]["recommended_target"],
        items=[classify_memory_data_item(p) for p in matches["memory_data_assets"]],
    )
    groups.append(mda)

    gui_items = matches["gui_roots"] + matches["gui_main_files"]
    gui_group = ConflictGroup(
        name="gui_root",
        description=CANONICAL_RULES["gui_root"]["description"],
        canonical_current=CANONICAL_RULES["gui_root"]["canonical_current"],
        recommended_target=CANONICAL_RULES["gui_root"]["recommended_target"],
        items=[classify_gui_item(p) for p in sorted(set(gui_items))],
    )
    groups.append(gui_group)

    dock_group = ConflictGroup(
        name="memory_dock",
        description=CANONICAL_RULES["memory_dock"]["description"],
        canonical_current=CANONICAL_RULES["memory_dock"]["canonical_current"],
        recommended_target=CANONICAL_RULES["memory_dock"]["recommended_target"],
        items=[classify_memory_dock_item(p) for p in matches["memory_dock_files"]],
    )
    groups.append(dock_group)

    dispatcher_group = ConflictGroup(
        name="dispatcher",
        description=CANONICAL_RULES["dispatcher"]["description"],
        canonical_current=CANONICAL_RULES["dispatcher"]["canonical_current"],
        recommended_target=CANONICAL_RULES["dispatcher"]["recommended_target"],
        items=[classify_dispatcher_item(p) for p in matches["dispatcher_files"]],
    )
    groups.append(dispatcher_group)

    model_group = ConflictGroup(
        name="model_engine",
        description=CANONICAL_RULES["model_engine"]["description"],
        canonical_current=CANONICAL_RULES["model_engine"]["canonical_current"],
        recommended_target=CANONICAL_RULES["model_engine"]["recommended_target"],
        items=[classify_model_engine_item(p) for p in matches["model_engine_assets"]],
    )
    groups.append(model_group)

    return groups


# =========================
# 架构规则诊断
# =========================

def analyze_architecture(root: Path, matches: Dict[str, List[str]]) -> List[ArchitectureIssue]:
    issues: List[ArchitectureIssue] = []

    core_gui_exists = (root / "core/gui").exists()
    top_gui_exists = (root / "gui").exists()
    aicore_memory_exists = (root / "core/aicore/memory").exists()
    aicore_model_engine_exists = (root / "core/aicore/model_engine.py").exists()
    aicore_model_engine2_exists = (root / "core/aicore/model_engine2.py").exists()
    legacy_core_version_exists = (root / "core/core2_0/1.0").exists()
    runtime_snapshot_exists = (root / "core/runtime_snapshot").exists()
    action_dispatcher_layer_exists = (root / "core/action_dispatcher").exists()
    canonical_dispatcher_exists = (root / "core/core2_0/sanhuatongyu/action_dispatcher.py").exists()

    if core_gui_exists and top_gui_exists:
        issues.append(
            ArchitectureIssue(
                severity="high",
                title="GUI 双轨并存",
                detail="同时存在 core/gui 与顶层 gui，容易形成两套界面真代码。",
                recommendation="保留 gui/ 作为唯一主 GUI；core/gui 退出主舞台，仅做过渡或迁移源。",
            )
        )

    if aicore_memory_exists:
        issues.append(
            ArchitectureIssue(
                severity="critical",
                title="AICore 内嵌旧记忆系统",
                detail="发现 core/aicore/memory/，且与 core/memory_engine 并存。",
                recommendation="统一 Memory 真相源到 core/memory_engine；core/aicore/memory/ 逐步退役。",
            )
        )

    memory_data_count = len(matches["memory_data_assets"])
    if memory_data_count >= 3:
        issues.append(
            ArchitectureIssue(
                severity="critical",
                title="记忆数据多真相源风险",
                detail=f"发现 {memory_data_count} 个 memory 侧写文件/资产，存在读写分叉风险。",
                recommendation="统一持久化入口到 data/memory/，并让所有读写都经由 core/memory_engine/memory_manager.py。",
            )
        )

    if aicore_model_engine_exists:
        issues.append(
            ArchitectureIssue(
                severity="high",
                title="ModelEngine 仍耦合在 AICore 内",
                detail="发现 core/aicore/model_engine.py，说明模型服务尚未完全外提。",
                recommendation="下一阶段建立 core/model_engine/，让 AICore 只做编排，不持有模型主实现。",
            )
        )

    if aicore_model_engine2_exists:
        issues.append(
            ArchitectureIssue(
                severity="high",
                title="存在 model_engine2 副本",
                detail="发现 core/aicore/model_engine2.py，说明 ModelEngine 仍未完成单一主线收敛。",
                recommendation="审计 model_engine 与 model_engine2 的引用与差异，保留一条主线。",
            )
        )

    if legacy_core_version_exists:
        issues.append(
            ArchitectureIssue(
                severity="medium",
                title="遗留版本目录仍在主树中",
                detail="发现 core/core2_0/1.0，说明旧版资产仍与当前主线共存。",
                recommendation="将 1.0 视为归档层，不再参与主链；必要时迁入 archive/legacy/。",
            )
        )

    if not runtime_snapshot_exists:
        issues.append(
            ArchitectureIssue(
                severity="medium",
                title="缺少 runtime_snapshot 层",
                detail="当前 core 下尚未发现 runtime_snapshot 目录。",
                recommendation="建议新增 core/runtime_snapshot/，统一提供系统快照、GUI 状态、动作回执聚合。",
            )
        )

    if not action_dispatcher_layer_exists and canonical_dispatcher_exists:
        issues.append(
            ArchitectureIssue(
                severity="medium",
                title="Dispatcher 尚未外提成独立层",
                detail="当前 Dispatcher 主实现仍嵌套在 core/core2_0/sanhuatongyu/ 中。",
                recommendation="短期内可继续以 sanhuatongyu 版本为 canonical；中期建议外提到 core/action_dispatcher/。",
            )
        )

    if len(matches["dispatcher_files"]) >= 2:
        issues.append(
            ArchitectureIssue(
                severity="high",
                title="Dispatcher 存在多份实现",
                detail=f"发现 {len(matches['dispatcher_files'])} 份 action_dispatcher.py。",
                recommendation="明确唯一生产实现；其余降为适配层、旧版归档或删除候选。",
            )
        )

    if len(matches["gui_main_files"]) >= 2:
        issues.append(
            ArchitectureIssue(
                severity="high",
                title="GUI 主入口重复",
                detail=f"发现 {len(matches['gui_main_files'])} 份 gui_main.py / main_gui.py。",
                recommendation="统一 gui/ 为主界面代码目录，其它仅保留轻量入口封装。",
            )
        )

    return issues


# =========================
# Mermaid 图
# =========================

def build_mermaid(conflict_groups: List[ConflictGroup], issues: List[ArchitectureIssue]) -> str:
    lines: List[str] = []
    lines.append("flowchart TD")
    lines.append('    AICore["core/aicore"]')
    lines.append('    Prompt["core/prompt_engine"]')
    lines.append('    Memory["core/memory_engine"]')
    lines.append('    System["core/system"]')
    lines.append('    GUI["gui/"]')
    lines.append('    Dispatcher["core/core2_0/sanhuatongyu/action_dispatcher.py\\n(current canonical)"]')
    lines.append('    Model["core/aicore/model_engine.py\\n(current primary)"]')
    lines.append('    FutureDispatcher["core/action_dispatcher/\\n(recommended target)"]')
    lines.append('    FutureModel["core/model_engine/\\n(recommended target)"]')
    lines.append('    MemoryData["data/memory/\\n(recommended truth source)"]')
    lines.append("")
    lines.append("    AICore --> Prompt")
    lines.append("    Prompt --> Memory")
    lines.append("    AICore --> Dispatcher")
    lines.append("    AICore --> Model")
    lines.append("    AICore --> System")
    lines.append("    GUI -. consume snapshot / memory .-> Memory")
    lines.append("    Memory --> MemoryData")
    lines.append("    Dispatcher -. future externalize .-> FutureDispatcher")
    lines.append("    Model -. future externalize .-> FutureModel")

    # 只挑高价值冲突挂在图上
    for group in conflict_groups:
        if not group.items:
            continue

        if group.name == "memory_manager":
            for idx, item in enumerate(group.items, start=1):
                node_name = f"MM{idx}"
                label = item.path.replace('"', "'")
                lines.append(f'    {node_name}["{label}"]')
                lines.append(f"    {node_name} -. {item.action} .-> Memory")

        if group.name == "gui_root":
            for idx, item in enumerate(group.items, start=1):
                node_name = f"GUIX{idx}"
                label = item.path.replace('"', "'")
                lines.append(f'    {node_name}["{label}"]')
                lines.append(f"    {node_name} -. {item.action} .-> GUI")

        if group.name == "dispatcher":
            for idx, item in enumerate(group.items, start=1):
                node_name = f"DP{idx}"
                label = item.path.replace('"', "'")
                lines.append(f'    {node_name}["{label}"]')
                lines.append(f"    {node_name} -. {item.action} .-> Dispatcher")

    if issues:
        lines.append("")
        lines.append("    subgraph Issues")
        for idx, issue in enumerate(issues[:6], start=1):
            node_name = f"ISS{idx}"
            label = issue.title.replace('"', "'")
            lines.append(f'        {node_name}["{label}"]')
        lines.append("    end")

    return "\n".join(lines) + "\n"


# =========================
# Markdown 报告
# =========================

def build_markdown(
    root: Path,
    files: List[Path],
    directories: List[Path],
    manifests: List[ManifestAudit],
    import_hits: List[ImportHit],
    conflict_groups: List[ConflictGroup],
    issues: List[ArchitectureIssue],
    output_files: Dict[str, str],
) -> str:
    lines: List[str] = []

    lines.append("# 三花聚顶结构审计报告")
    lines.append("")
    lines.append(f"- 生成时间：`{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`")
    lines.append(f"- 项目根目录：`{root.as_posix()}`")
    lines.append(f"- 扫描目录数：`{len(directories)}`")
    lines.append(f"- 扫描文件数：`{len(files)}`")
    lines.append(f"- manifest 数量：`{len(manifests)}`")
    lines.append(f"- 旧路径 import 命中：`{len(import_hits)}`")
    lines.append("")

    lines.append("## 一、核心判断")
    lines.append("")
    lines.append("- 记忆层主骨架已经存在：`core/memory_engine` + `core/prompt_engine`。")
    lines.append("- 但当前存在 **memory / gui / model_engine / dispatcher** 多轨并存问题。")
    lines.append("- 当前最合适的治理策略是：**先审计、再迁移、最后删除**。")
    lines.append("")

    lines.append("## 二、推荐定版方向")
    lines.append("")
    lines.append("- **记忆真相源**：`core/memory_engine/`")
    lines.append("- **Prompt 记忆桥**：`core/prompt_engine/prompt_memory_bridge.py`")
    lines.append("- **GUI 唯一主目录**：`gui/`")
    lines.append("- **Dispatcher 当前 canonical**：`core/core2_0/sanhuatongyu/action_dispatcher.py`")
    lines.append("- **ModelEngine 当前主线（待外提）**：`core/aicore/model_engine.py`")
    lines.append("- **记忆数据推荐统一落点**：`data/memory/`")
    lines.append("")

    lines.append("## 三、架构问题")
    lines.append("")
    issue_rows = [
        [i.severity, i.title, i.detail, i.recommendation]
        for i in issues
    ]
    lines.append(make_table(["级别", "问题", "详情", "建议"], issue_rows))

    lines.append("## 四、冲突组")
    lines.append("")
    for group in conflict_groups:
        lines.append(f"### 4.{conflict_groups.index(group) + 1} {group.name}")
        lines.append("")
        lines.append(f"- 说明：{group.description}")
        lines.append(f"- 当前 canonical：`{group.canonical_current}`")
        lines.append(f"- 推荐目标：`{group.recommended_target}`")
        lines.append("")
        rows = [
            [item.path, item.action, item.note, item.recommended_target or ""]
            for item in group.items
        ]
        lines.append(make_table(["路径", "动作", "说明", "推荐目标"], rows))

    lines.append("## 五、旧路径 import 命中")
    lines.append("")
    if import_hits:
        rows = [[hit.importer, hit.imported, hit.matched_prefix] for hit in import_hits]
        lines.append(make_table(["导入方", "导入路径", "命中规则"], rows))
    else:
        lines.append("_未发现旧路径 import 命中。_\n")

    lines.append("## 六、Manifest 审计")
    lines.append("")
    manifest_rows = []
    for m in manifests:
        manifest_rows.append([
            m.path,
            m.scope,
            m.module_dir,
            m.name_in_manifest or "",
            m.entry or "",
            "Y" if m.entry_exists else ("N" if m.entry_exists is False else ""),
            m.entry_class or "",
            "Y" if m.entry_class_exists else ("N" if m.entry_class_exists is False else ""),
            "; ".join(m.issues),
        ])
    lines.append(make_table(
        ["manifest", "scope", "module_dir", "name", "entry", "entry_exists", "entry_class", "entry_class_ok", "issues"],
        manifest_rows,
    ))

    lines.append("## 七、输出文件")
    lines.append("")
    out_rows = [[k, v] for k, v in output_files.items()]
    lines.append(make_table(["文件类型", "路径"], out_rows))

    lines.append("## 八、立即可执行的下一步")
    lines.append("")
    lines.append("1. 先把 `core/memory_engine` 定为唯一 Memory 真相源。")
    lines.append("2. 停止在 `core/aicore/memory/` 上继续加功能。")
    lines.append("3. 把 GUI 真代码只收敛到 `gui/`。")
    lines.append("4. 明确 `core/core2_0/sanhuatongyu/action_dispatcher.py` 为当前 Dispatcher 正式实现。")
    lines.append("5. 下一步再写 `sanhua_migrate.py` 做半自动迁移，而不是直接手删。")
    lines.append("")

    return "\n".join(lines)


# =========================
# 主流程
# =========================

def build_migration_plan(conflict_groups: List[ConflictGroup]) -> List[Dict[str, str]]:
    plan: List[Dict[str, str]] = []

    for group in conflict_groups:
        for item in group.items:
            plan.append({
                "group": group.name,
                "path": item.path,
                "action": item.action,
                "note": item.note,
                "recommended_target": item.recommended_target or "",
            })

    return plan


def summarize_import_hits(import_hits: List[ImportHit]) -> Dict[str, Any]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for hit in import_hits:
        bucket = grouped.setdefault(hit.matched_prefix, {"count": 0, "importers": []})
        bucket["count"] += 1
        bucket["importers"].append(hit.importer)

    for prefix, payload in grouped.items():
        payload["importers"] = sorted(set(payload["importers"]))

    return grouped


def main() -> int:
    parser = argparse.ArgumentParser(description="三花聚顶结构审计脚本（只读版）")
    parser.add_argument(
        "--root",
        default=".",
        help="项目根目录，默认当前目录",
    )
    parser.add_argument(
        "--reports-dir",
        default="reports",
        help="报告输出目录，默认 reports",
    )
    parser.add_argument(
        "--include-third-party",
        action="store_true",
        help="是否包含第三方/大目录（默认关闭，不建议）",
    )
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.exists():
        print(f"[ERROR] 根目录不存在: {root}", file=sys.stderr)
        return 2

    reports_dir = (root / args.reports_dir).resolve()
    ensure_dir(reports_dir)

    directories, files = iter_project_paths(root, include_third_party=args.include_third_party)

    py_files = [f for f in files if f.suffix == ".py"]
    manifests = scan_manifests(files, root)
    import_hits = scan_imports(py_files, root)
    matches = collect_matching(files, directories, root)
    conflict_groups = build_conflict_groups(matches)
    issues = analyze_architecture(root, matches)
    migration_plan = build_migration_plan(conflict_groups)
    mermaid = build_mermaid(conflict_groups, issues)

    ts = now_ts()
    prefix = reports_dir / f"sanhua_audit_{ts}"

    summary = {
        "generated_at": datetime.now().isoformat(),
        "root": root.as_posix(),
        "scanned_directories": len(directories),
        "scanned_files": len(files),
        "python_files": len(py_files),
        "manifest_count": len(manifests),
        "legacy_import_hits_count": len(import_hits),
        "matches": matches,
        "canonical_rules": CANONICAL_RULES,
        "architecture_issues": [asdict(x) for x in issues],
        "legacy_import_hits": [asdict(x) for x in import_hits],
        "legacy_import_summary": summarize_import_hits(import_hits),
        "manifests": [asdict(x) for x in manifests],
    }

    conflicts_json = {
        "generated_at": datetime.now().isoformat(),
        "groups": [
            {
                "name": g.name,
                "description": g.description,
                "canonical_current": g.canonical_current,
                "recommended_target": g.recommended_target,
                "items": [asdict(i) for i in g.items],
            }
            for g in conflict_groups
        ]
    }

    migration_json = {
        "generated_at": datetime.now().isoformat(),
        "plan": migration_plan,
    }

    output_files = {
        "summary_json": str(prefix.with_suffix(".json").relative_to(root)),
        "conflicts_json": str((reports_dir / f"sanhua_conflicts_{ts}.json").relative_to(root)),
        "migration_json": str((reports_dir / f"sanhua_migration_plan_{ts}.json").relative_to(root)),
        "report_md": str((reports_dir / f"sanhua_report_{ts}.md").relative_to(root)),
        "mermaid_mmd": str((reports_dir / f"sanhua_architecture_{ts}.mmd").relative_to(root)),
    }

    markdown_report = build_markdown(
        root=root,
        files=files,
        directories=directories,
        manifests=manifests,
        import_hits=import_hits,
        conflict_groups=conflict_groups,
        issues=issues,
        output_files=output_files,
    )

    write_json(prefix.with_suffix(".json"), summary)
    write_json(reports_dir / f"sanhua_conflicts_{ts}.json", conflicts_json)
    write_json(reports_dir / f"sanhua_migration_plan_{ts}.json", migration_json)
    write_text(reports_dir / f"sanhua_report_{ts}.md", markdown_report)
    write_text(reports_dir / f"sanhua_architecture_{ts}.mmd", mermaid)

    # latest 覆盖版，方便你重复跑
    write_json(reports_dir / "sanhua_audit_latest.json", summary)
    write_json(reports_dir / "sanhua_conflicts_latest.json", conflicts_json)
    write_json(reports_dir / "sanhua_migration_plan_latest.json", migration_json)
    write_text(reports_dir / "sanhua_report_latest.md", markdown_report)
    write_text(reports_dir / "sanhua_architecture_latest.mmd", mermaid)

    # 终端摘要
    print("=" * 72)
    print("三花聚顶结构审计完成")
    print("=" * 72)
    print(f"项目根目录            : {root}")
    print(f"扫描目录数            : {len(directories)}")
    print(f"扫描文件数            : {len(files)}")
    print(f"manifest 数量         : {len(manifests)}")
    print(f"旧路径 import 命中    : {len(import_hits)}")
    print(f"架构问题数            : {len(issues)}")
    print("-" * 72)
    print("输出文件：")
    for k, v in output_files.items():
        print(f"  - {k:18s}: {v}")
    print("-" * 72)

    # 重点摘要
    print("重点问题摘要：")
    for issue in issues[:8]:
        print(f"  [{issue.severity.upper()}] {issue.title} -> {issue.recommendation}")

    print("-" * 72)
    print("冲突组摘要：")
    for group in conflict_groups:
        print(f"  - {group.name:20s}: {len(group.items)} 项")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
