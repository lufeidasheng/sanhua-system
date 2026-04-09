#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
三花聚顶系统 · 静态结构与模块关系审计脚本 v2.2

定位：
- 这是“静态基础审计器”，不是最终真相裁判
- 用于发现目录/manifest/import/静态入口/别名/明显边界问题
- 不直接替代运行时调度真相

v2.2 修正：
1. GUI 耦合判定降噪：优先看 import/from_import/call，不再用字符串常量硬判
2. dispatch_integration 只针对“动作层模块”审计，降低服务层/桥接层误报
3. aliases.yaml 按 list schema（name/keywords/function）正确审计，只重点校验 function
4. 保留 v2.1 的：
   - __init__.py 相对导入解析修正
   - static_entry_reachability 命名修正
   - 同时支持 modules/ 与 模块/
   - alias 审计延后
   - 核心组件显式路径优先
   - 强化排除规则，避免 venv / 导出包 / 审计输出污染
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


EXCLUDED_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    "venv",
    ".venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".next",
    ".turbo",
    "_audit",
    "_audit_v2",
    "_audit_v2_clean",
    "_chatgpt_project_bundle_v2",
    "第一波",
    "_legacy_disabled",
    "bin",
    "include",
    "lib",
    "share",
    "site-packages",
    "fix_backups",
    "rollback_snapshots_runtime",
}

EXCLUDED_PATH_PARTS = {
    "/site-packages/",
    "/_audit/",
    "/_audit_v2/",
    "/_audit_v2_clean/",
    "/_chatgpt_project_bundle_v2/",
    "/第一波/",
    "/_legacy_disabled/",
    "/fix_backups/",
    "/rollback_snapshots_runtime/",
}

PYTHON_EXTENSIONS = {".py"}
TEXT_EXTENSIONS = {".py", ".json", ".yaml", ".yml", ".toml", ".md", ".txt", ".csv", ".dot"}

DISPATCH_KEYWORDS = {
    "dispatch_action",
    "call_action",
    "QuantumActionDispatcher",
    "action_dispatcher",
    "ActionDispatcher",
    "ACTION_MANAGER",
    "register_action",
    "execute_action",
    "register_actions",
}

# v2.2: GUI 关键词只用于 import/from_import/call 级证据，不用于字符串常量误判
GUI_IMPORT_KEYWORDS = {
    "entry.gui",
    "entry.gui_entry",
    "gui_main",
    "gui_entry",
    "memory_dock",
    "tkinter",
    "PyQt",
    "PySide",
    "streamlit",
    "gradio",
    "nicegui",
    "flet",
    "qt",
}

ENTRY_SEED_CANDIDATES = [
    "entry/gui_entry/gui_main.py",
    "entry/gui_main.py",
    "core/aicore/aicore.py",
    "core/core2_0/sanhuatongyu/action_dispatcher.py",
    "main.py",
    "app.py",
    "run.py",
    "start.py",
]

ACTIONISH_KEYWORDS = {
    "execute",
    "dispatch",
    "action",
    "intent",
    "plugin",
    "handler",
    "tool",
    "invoke",
    "router",
}

DEFAULT_REQUIRED_MANIFEST_FIELDS = ["name", "version"]
DEFAULT_RECOMMENDED_MANIFEST_FIELDS = ["description", "entry", "dependencies"]

MODULE_ROOT_CANDIDATES = ["modules", "模块"]

CORE_COMPONENT_PATHS: Dict[str, List[str]] = {
    "AICore": [
        "core/aicore/aicore.py",
        "core/aicore/extensible_aicore.py",
    ],
    "MemoryManager": [
        "core/memory_engine/memory_manager.py",
        "core/aicore/memory/memory_manager.py",
    ],
    "PromptMemoryBridge": [
        "core/prompt_engine/prompt_memory_bridge.py",
    ],
    "ModelEngine": [
        "core/aicore/model_engine.py",
        "core/aicore/model_engine2.py",
        "core/core2_0/sanhuatongyu/services/model_engine/engine.py",
    ],
    "SystemMonitor": [
        "modules/system_monitor/module.py",
    ],
    "QuantumActionDispatcher": [
        "core/core2_0/sanhuatongyu/action_dispatcher.py",
    ],
}

# 这些更像服务层 / 桥接层 / 核心能力层，不默认纳入“统一调度缺失”审计
NON_ACTION_CORE_COMPONENTS = {
    "MemoryManager",
    "PromptMemoryBridge",
    "ModelEngine",
}

# 如果 manifest 明确有 actions 字段，则可视为动作层模块
MANIFEST_ACTION_KEYS = {"actions", "action", "tools", "handlers"}

# 明显属于入口/GUI层的模块名提示
GUI_LAYER_NAME_HINTS = {"gui_entry", "gui", "memory_dock"}


@dataclass
class FileNode:
    path: str
    module_name: str
    imports: Set[str] = field(default_factory=set)
    import_targets: Set[str] = field(default_factory=set)
    from_imports: Set[str] = field(default_factory=set)
    calls: Set[str] = field(default_factory=set)
    classes: List[str] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    strings: Set[str] = field(default_factory=set)
    syntax_error: Optional[str] = None


@dataclass
class ManifestAudit:
    exists: bool
    path: Optional[str] = None
    valid_json: bool = False
    data: Dict[str, Any] = field(default_factory=dict)
    missing_required: List[str] = field(default_factory=list)
    missing_recommended: List[str] = field(default_factory=list)
    entry_declared: Optional[str] = None
    entry_exists: Optional[bool] = None
    entry_kind: Optional[str] = None
    issues: List[str] = field(default_factory=list)


@dataclass
class ModuleRecord:
    name: str
    kind: str
    path: str
    root_group: str = ""
    manifest: ManifestAudit = field(default_factory=lambda: ManifestAudit(exists=False))
    files: List[str] = field(default_factory=list)
    entry_candidates: List[str] = field(default_factory=list)
    declared_dependencies: List[str] = field(default_factory=list)
    static_dependencies: List[str] = field(default_factory=list)
    depended_by: List[str] = field(default_factory=list)
    dispatch_integration: str = "unknown"
    gui_integration: str = "unknown"
    static_entry_reachability: str = "unknown"
    status: str = "unknown"
    owners: List[str] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    alias_functions: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    score: int = 0
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditSummary:
    project_root: str
    total_python_files: int
    total_modules: int
    total_core_components: int
    entry_seeds: List[str]
    blockers: List[Dict[str, Any]]


class ProjectAuditor:
    def __init__(
        self,
        root: Path,
        output_dir: Path,
        required_manifest_fields: Optional[List[str]] = None,
        recommended_manifest_fields: Optional[List[str]] = None,
    ) -> None:
        self.root = root.resolve()
        self.output_dir = output_dir.resolve()
        self.required_manifest_fields = required_manifest_fields or DEFAULT_REQUIRED_MANIFEST_FIELDS
        self.recommended_manifest_fields = recommended_manifest_fields or DEFAULT_RECOMMENDED_MANIFEST_FIELDS

        self.file_nodes: Dict[str, FileNode] = {}
        self.path_to_module_name: Dict[str, str] = {}
        self.module_name_to_paths: Dict[str, Set[str]] = defaultdict(set)
        self.reverse_import_graph: Dict[str, Set[str]] = defaultdict(set)
        self.import_graph: Dict[str, Set[str]] = defaultdict(set)
        self.reachable_from_entries: Set[str] = set()
        self.module_records: Dict[str, ModuleRecord] = {}
        self.alias_map: Any = {}
        self.alias_issues: List[str] = []
        self.syntax_errors: List[Tuple[str, str]] = []
        self.entry_seeds: List[str] = []

        # alias function -> keywords / names
        self.alias_function_to_labels: Dict[str, List[str]] = defaultdict(list)

    # -------------------------
    # Public API
    # -------------------------
    def run(self) -> Dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._discover_python_files()
        self._parse_python_files()
        self._resolve_import_graph()
        self._discover_entry_seeds()
        self._compute_reachability()

        self._load_aliases_raw()
        self._discover_modules_dir_modules()
        self._discover_core_components()
        self._attach_module_relationships()
        self._audit_aliases_after_modules()
        self._score_and_finalize_modules()
        blockers = self._build_blockers()

        summary = AuditSummary(
            project_root=str(self.root),
            total_python_files=len(self.file_nodes),
            total_modules=len([m for m in self.module_records.values() if m.kind == "module"]),
            total_core_components=len([m for m in self.module_records.values() if m.kind == "core_component"]),
            entry_seeds=self.entry_seeds,
            blockers=blockers,
        )

        payload = {
            "summary": asdict(summary),
            "aliases": {
                "path": self._relative_or_none(self.root / "config" / "aliases.yaml"),
                "count": self._alias_count(),
                "issues": self.alias_issues,
                "schema": self._alias_schema_name(),
            },
            "syntax_errors": [
                {"path": path, "error": error} for path, error in self.syntax_errors
            ],
            "modules": [self._module_to_dict(m) for m in self._sorted_modules()],
        }

        self._write_json(payload)
        self._write_markdown(payload)
        self._write_graphviz(payload)
        return payload

    # -------------------------
    # Discovery
    # -------------------------
    def _should_skip_dirpath(self, path: Path) -> bool:
        rel = self._relative_or_none(path)
        rel = "/" + rel.strip("/") + "/" if rel else "/"
        return any(part in rel for part in EXCLUDED_PATH_PARTS)

    def _iter_files(self, suffixes: Optional[Set[str]] = None) -> Iterable[Path]:
        for dirpath, dirnames, filenames in os.walk(self.root):
            current_dir = Path(dirpath)

            if self._should_skip_dirpath(current_dir):
                dirnames[:] = []
                continue

            dirnames[:] = [
                d for d in dirnames
                if d not in EXCLUDED_DIRS
                and not self._should_skip_dirpath(current_dir / d)
            ]

            for filename in filenames:
                path = current_dir / filename
                if suffixes and path.suffix not in suffixes:
                    continue
                yield path

    def _discover_python_files(self) -> None:
        for path in self._iter_files(PYTHON_EXTENSIONS):
            rel = self._rel(path)
            module_name = self._path_to_import_name(rel)
            self.path_to_module_name[rel] = module_name
            self.module_name_to_paths[module_name].add(rel)
            self.file_nodes[rel] = FileNode(path=rel, module_name=module_name)

            if path.name == "__init__.py":
                pkg_name = module_name.rsplit(".__init__", 1)[0]
                self.module_name_to_paths[pkg_name].add(rel)

    def _parse_python_files(self) -> None:
        for rel, node in self.file_nodes.items():
            abs_path = self.root / rel
            try:
                source = abs_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                source = abs_path.read_text(encoding="utf-8", errors="ignore")

            try:
                tree = ast.parse(source, filename=str(abs_path))
            except SyntaxError as e:
                msg = f"SyntaxError:{e.lineno}:{e.offset}: {e.msg}"
                node.syntax_error = msg
                self.syntax_errors.append((rel, msg))
                continue

            for child in ast.walk(tree):
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        node.imports.add(alias.name)
                elif isinstance(child, ast.ImportFrom):
                    mod = child.module or ""
                    resolved = self._resolve_relative_import(node.module_name, mod, child.level)
                    if resolved:
                        node.from_imports.add(resolved)
                    for alias in child.names:
                        if resolved:
                            node.imports.add(f"{resolved}.{alias.name}")
                elif isinstance(child, ast.Call):
                    fn_name = self._get_call_name(child.func)
                    if fn_name:
                        node.calls.add(fn_name)
                elif isinstance(child, ast.ClassDef):
                    node.classes.append(child.name)
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    node.functions.append(child.name)
                elif isinstance(child, ast.Constant) and isinstance(child.value, str):
                    text = child.value.strip()
                    if text and len(text) <= 200:
                        node.strings.add(text)

    def _resolve_import_graph(self) -> None:
        for rel, node in self.file_nodes.items():
            possible_targets: Set[str] = set()
            imported_names = set(node.imports) | set(node.from_imports)
            for imported in imported_names:
                for candidate in self._resolve_import_name_to_paths(imported):
                    possible_targets.add(candidate)
            node.import_targets = possible_targets
            self.import_graph[rel] = possible_targets
            for target in possible_targets:
                self.reverse_import_graph[target].add(rel)

    def _discover_entry_seeds(self) -> None:
        seeds: List[str] = []
        for rel in ENTRY_SEED_CANDIDATES:
            if (self.root / rel).exists():
                seeds.append(rel)

        if not seeds:
            for candidate in ["gui_main", "main", "app", "run", "start"]:
                for rel in self.file_nodes:
                    if rel.endswith(f"/{candidate}.py") or rel == f"{candidate}.py":
                        seeds.append(rel)

        self.entry_seeds = sorted(dict.fromkeys(seeds))

    def _compute_reachability(self) -> None:
        visited: Set[str] = set()
        queue: deque[str] = deque(self.entry_seeds)

        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            for nxt in self.import_graph.get(current, set()):
                if nxt not in visited:
                    queue.append(nxt)
        self.reachable_from_entries = visited

    def _load_aliases_raw(self) -> None:
        alias_path = self.root / "config" / "aliases.yaml"
        if not alias_path.exists():
            self.alias_issues.append("config/aliases.yaml 不存在")
            return
        if yaml is None:
            self.alias_issues.append("未安装 PyYAML，无法解析 aliases.yaml")
            return
        try:
            data = yaml.safe_load(alias_path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            self.alias_issues.append(f"aliases.yaml 解析失败: {e}")
            return
        self.alias_map = data

    def _discover_modules_dir_modules(self) -> None:
        for root_name in MODULE_ROOT_CANDIDATES:
            modules_root = self.root / root_name
            if not modules_root.exists():
                continue

            for child in sorted(modules_root.iterdir()):
                if not child.is_dir() or child.name in EXCLUDED_DIRS:
                    continue
                if self._should_skip_dirpath(child):
                    continue

                name = f"{root_name}/{child.name}" if root_name == "模块" else child.name
                manifest = self._audit_manifest(child)
                files = self._list_module_files(child)
                entry_candidates = self._discover_entry_candidates(child, manifest)

                record = ModuleRecord(
                    name=name,
                    kind="module",
                    path=self._rel(child),
                    root_group=root_name,
                    manifest=manifest,
                    files=files,
                    entry_candidates=entry_candidates,
                    declared_dependencies=self._extract_manifest_dependencies(manifest.data),
                )
                self.module_records[name] = record

    def _discover_core_components(self) -> None:
        for component_name, candidate_paths in CORE_COMPONENT_PATHS.items():
            found_path: Optional[Path] = None
            for rel in candidate_paths:
                abs_path = self.root / rel
                if abs_path.exists():
                    found_path = abs_path
                    break

            if not found_path:
                continue

            rel = self._rel(found_path)
            record = ModuleRecord(
                name=component_name,
                kind="core_component",
                path=rel,
                root_group="core",
                manifest=ManifestAudit(exists=False),
                files=[rel],
                entry_candidates=[rel],
            )
            self.module_records[component_name] = record

    # -------------------------
    # Auditing
    # -------------------------
    def _audit_manifest(self, module_dir: Path) -> ManifestAudit:
        manifest_path = module_dir / "manifest.json"
        audit = ManifestAudit(exists=manifest_path.exists(), path=self._relative_or_none(manifest_path))
        if not manifest_path.exists():
            audit.issues.append("manifest.json 缺失")
            return audit

        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            audit.valid_json = True
            audit.data = data if isinstance(data, dict) else {}
        except Exception as e:
            audit.issues.append(f"manifest.json 非法 JSON: {e}")
            return audit

        for field_name in self.required_manifest_fields:
            if field_name not in audit.data:
                audit.missing_required.append(field_name)
        for field_name in self.recommended_manifest_fields:
            if field_name not in audit.data:
                audit.missing_recommended.append(field_name)

        entry_value = self._first_existing_key(
            audit.data,
            [
                "entry",
                "main",
                "module",
                "bootstrap",
                "entrypoint",
                "python_entry",
                "entry_class",
            ],
        )
        if isinstance(entry_value, str):
            audit.entry_declared = entry_value
            entry_exists, entry_kind, detail_issue = self._resolve_manifest_entry(module_dir, entry_value)
            audit.entry_exists = entry_exists
            audit.entry_kind = entry_kind
            if detail_issue:
                audit.issues.append(detail_issue)
        elif entry_value is not None:
            audit.issues.append("manifest entry 字段不是字符串")

        return audit

    def _resolve_manifest_entry(self, module_dir: Path, entry_value: str) -> Tuple[bool, str, Optional[str]]:
        text = entry_value.strip()

        if "/" in text or text.endswith(".py"):
            file_part = text.split(":", 1)[0]
            candidate = module_dir / file_part
            if candidate.exists():
                return True, "relative_file", None
            return False, "relative_file", f"manifest entry 不存在: {entry_value}"

        if ":" in text:
            left, _right = text.split(":", 1)
            if left.endswith(".py"):
                candidate = module_dir / left
                if candidate.exists():
                    return True, "file_colon_symbol", None
                return False, "file_colon_symbol", f"manifest entry 文件不存在: {entry_value}"

            resolved = self._resolve_import_name_to_paths(left)
            if resolved:
                return True, "import_path_colon_symbol", None
            return False, "import_path_colon_symbol", f"manifest entry import 路径不存在: {entry_value}"

        maybe_module_name = text
        resolved = self._resolve_import_name_to_paths(maybe_module_name)
        if resolved:
            return True, "import_path", None

        if "." in text:
            module_part = text.rsplit(".", 1)[0]
            resolved = self._resolve_import_name_to_paths(module_part)
            if resolved:
                return True, "import_path_symbol", None

        return False, "unknown", f"manifest entry 无法解析: {entry_value}"

    def _attach_module_relationships(self) -> None:
        file_to_module: Dict[str, str] = {}
        for mod in self.module_records.values():
            for rel in mod.files:
                file_to_module[rel] = mod.name

        for mod in self.module_records.values():
            dependency_counter: Counter[str] = Counter()
            imported_by_counter: Counter[str] = Counter()
            dispatch_hits: List[str] = []
            gui_hits: List[str] = []
            reach_hits: List[str] = []

            for rel in mod.files:
                node = self.file_nodes.get(rel)
                if not node:
                    continue

                for target_file in node.import_targets:
                    target_module = file_to_module.get(target_file)
                    if target_module and target_module != mod.name:
                        dependency_counter[target_module] += 1

                for source_file in self.reverse_import_graph.get(rel, set()):
                    source_module = file_to_module.get(source_file)
                    if source_module and source_module != mod.name:
                        imported_by_counter[source_module] += 1

                if self._file_uses_dispatch(node):
                    dispatch_hits.append(rel)
                if self._file_uses_gui(node):
                    gui_hits.append(rel)
                if rel in self.reachable_from_entries:
                    reach_hits.append(rel)

            mod.static_dependencies = sorted(dependency_counter)
            mod.depended_by = sorted(imported_by_counter)
            mod.dispatch_integration = self._judge_dispatch(mod, dispatch_hits)
            mod.gui_integration = self._judge_gui(mod, gui_hits)
            mod.static_entry_reachability = self._judge_reachability(mod, reach_hits)
            mod.evidence.update(
                {
                    "dispatch_hits": dispatch_hits[:20],
                    "gui_hits": gui_hits[:20],
                    "static_reachable_files": reach_hits[:20],
                    "dependency_edges": dict(dependency_counter),
                    "imported_by_edges": dict(imported_by_counter),
                }
            )

            self._append_module_issues(mod)

    def _audit_aliases_after_modules(self) -> None:
        if not self.alias_map:
            return

        known_actionish_names = self._collect_known_actionish_names()
        known_actionish_names_lower = {x.lower() for x in known_actionish_names}
        module_search_pools = {
            mod.name: " ".join(
                [
                    mod.name,
                    mod.path,
                    *mod.entry_candidates,
                    *mod.declared_dependencies,
                ]
            ).lower()
            for mod in self.module_records.values()
        }

        # --- 情况 1：当前 aliases.yaml 是 list schema ---
        # 每项通常长这样：{name, keywords, function}
        if isinstance(self.alias_map, list):
            for idx, item in enumerate(self.alias_map):
                if not isinstance(item, dict):
                    self.alias_issues.append(f"aliases[{idx}] 不是对象")
                    continue

                func = item.get("function")
                name = item.get("name")
                keywords = item.get("keywords", [])

                if not isinstance(func, str) or not func.strip():
                    self.alias_issues.append(f"aliases[{idx}] 缺少有效 function 字段")
                    continue

                func = func.strip()
                func_lower = func.lower()

                matched_module = False
                for mod in self.module_records.values():
                    pool = module_search_pools[mod.name]
                    if func_lower in pool or mod.name.lower() in func_lower or mod.path.lower() in func_lower:
                        matched_module = True
                        mod.alias_functions.append(func)
                        if isinstance(name, str) and name.strip():
                            mod.aliases.append(name.strip())
                        if isinstance(keywords, list):
                            for kw in keywords:
                                if isinstance(kw, str) and kw.strip():
                                    mod.aliases.append(kw.strip())

                if not matched_module and func_lower not in known_actionish_names_lower:
                    self.alias_issues.append(f"aliases[{idx}].function -> '{func}' 未匹配到已知模块/动作名")

            # 去重
            for mod in self.module_records.values():
                mod.aliases = sorted(dict.fromkeys(mod.aliases))
                mod.alias_functions = sorted(dict.fromkeys(mod.alias_functions))
            return

        # --- 情况 2：dict / 其他 schema，保守退化 ---
        pairs = self._flatten_alias_pairs(self.alias_map)
        for alias, target in pairs:
            target_text = str(target).strip()
            target_lower = target_text.lower()
            matched_module = False

            for mod in self.module_records.values():
                pool = module_search_pools[mod.name]
                if mod.name.lower() in target_lower or mod.path.lower() in target_lower or target_lower in pool:
                    mod.aliases.append(alias)
                    matched_module = True

            if "/" in target_text:
                path_guess = self.root / target_text
                if not path_guess.exists():
                    self.alias_issues.append(f"alias '{alias}' -> '{target_text}' 疑似悬挂路径")
                continue

            if matched_module:
                continue

            if known_actionish_names and target_lower not in known_actionish_names_lower:
                self.alias_issues.append(f"alias '{alias}' -> '{target_text}' 未匹配到已知模块/动作名")

        for mod in self.module_records.values():
            mod.aliases = sorted(dict.fromkeys(mod.aliases))

    def _collect_known_actionish_names(self) -> Set[str]:
        names: Set[str] = set()
        for rel, node in self.file_nodes.items():
            for fn in node.functions:
                if any(k in fn.lower() for k in ACTIONISH_KEYWORDS):
                    names.add(fn)
            for cls in node.classes:
                if any(k in cls.lower() for k in ACTIONISH_KEYWORDS):
                    names.add(cls)
            for call in node.calls:
                if any(k in call.lower() for k in ACTIONISH_KEYWORDS):
                    names.add(call)
        return names

    def _score_and_finalize_modules(self) -> None:
        for mod in self.module_records.values():
            score = 0

            if mod.kind == "module":
                if not mod.manifest.exists:
                    score += 30
                if mod.manifest.missing_required:
                    score += 20
                if mod.manifest.entry_declared and mod.manifest.entry_exists is False:
                    score += 20
                if not mod.entry_candidates:
                    score += 10

            if mod.static_entry_reachability == "not_reachable":
                score += 10
            elif mod.static_entry_reachability == "partially_reachable":
                score += 4

            if mod.dispatch_integration == "bypassing_or_missing":
                score += 15
            elif mod.dispatch_integration == "unknown":
                score += 5

            if mod.gui_integration == "direct_coupling":
                score += 12

            if mod.kind == "module" and not mod.depended_by:
                score += 3

            if mod.name in {"AICore", "QuantumActionDispatcher", "MemoryManager", "ModelEngine"} and mod.static_entry_reachability == "not_reachable":
                score += 15

            mod.score = score
            mod.status = self._final_status(mod)

    def _build_blockers(self) -> List[Dict[str, Any]]:
        blockers: List[Dict[str, Any]] = []

        missing_manifest = [
            m.name for m in self._sorted_modules()
            if m.kind == "module" and (not m.manifest.exists or m.manifest.missing_required)
        ]
        if missing_manifest:
            blockers.append(
                {
                    "title": "manifest 治理不完整",
                    "severity": "critical",
                    "why": "modules/ 或 模块/ 下存在缺失 manifest 或缺少关键字段的模块，系统无法形成可信模块注册表。",
                    "affected_modules": missing_manifest[:20],
                    "recommendation": "先统一 manifest 最低标准（name/version/description/entry/dependencies），再把审计纳入 CI。",
                }
            )

        not_reachable = [
            m.name for m in self._sorted_modules()
            if m.static_entry_reachability == "not_reachable"
        ]
        if not_reachable:
            blockers.append(
                {
                    "title": "存在静态入口不可达的模块/核心组件",
                    "severity": "high",
                    "why": "静态可达性显示部分模块没有从 GUI / AICore / dispatcher 入口链路静态触达；这不等于运行时一定不可达，但说明主链可见性较差。",
                    "affected_modules": not_reachable[:20],
                    "recommendation": "把“静态入口可达性”和“运行时接入性”分开治理；未静态触达模块要么补接线，要么明确为 manifest/dispatcher 动态模块。",
                }
            )

        dispatch_bypass = [
            m.name for m in self._sorted_modules()
            if m.dispatch_integration == "bypassing_or_missing"
        ]
        if dispatch_bypass:
            blockers.append(
                {
                    "title": "统一调度接入不完整",
                    "severity": "high",
                    "why": "部分动作层模块具备 action / intent / handler 特征，但未检测到明显通过 dispatch_action / call_action / QuantumActionDispatcher 接入。",
                    "affected_modules": dispatch_bypass[:20],
                    "recommendation": "把动作调用统一收口到 dispatch_action / call_action，并结合运行时注册信息做第二层校验。",
                }
            )

        gui_coupling = [
            m.name for m in self._sorted_modules()
            if m.gui_integration == "direct_coupling"
        ]
        if gui_coupling:
            blockers.append(
                {
                    "title": "GUI 与模块存在直接耦合",
                    "severity": "high",
                    "why": "检测到模块内部存在 GUI import / from import / 调用级证据，可能破坏“GUI 只负责显示/输入/转发”的边界。",
                    "affected_modules": gui_coupling[:20],
                    "recommendation": "把 GUI 依赖抽到适配层或事件桥，模块只暴露标准动作与数据。",
                }
            )

        if self.alias_issues:
            blockers.append(
                {
                    "title": "aliases 配置存在悬挂或不可解析项",
                    "severity": "medium",
                    "why": "别名配置与实际模块/入口/动作名不一致，会导致调度、映射和治理视图失真。",
                    "affected_modules": [],
                    "recommendation": "清理悬挂 alias，并让 alias 校验纳入审计脚本。",
                    "evidence": self.alias_issues[:20],
                }
            )

        blockers.sort(
            key=lambda x: {"critical": 3, "high": 2, "medium": 1}.get(x.get("severity", "medium"), 0),
            reverse=True,
        )
        return blockers[:3]

    # -------------------------
    # Decisions & rules
    # -------------------------
    def _is_action_layer_module(self, mod: ModuleRecord) -> bool:
        # dispatcher 核心本身算动作层
        if mod.name == "QuantumActionDispatcher":
            return True

        # 服务层/桥接层核心组件默认不纳入
        if mod.kind == "core_component" and mod.name in NON_ACTION_CORE_COMPONENTS:
            return False

        # GUI 层不拿去做调度缺失判断
        if mod.gui_integration == "gui_layer":
            return False

        # manifest 明确声明 actions/handlers/tools
        if isinstance(mod.manifest.data, dict):
            if any(key in mod.manifest.data for key in MANIFEST_ACTION_KEYS):
                return True

        # modules / 模块 下默认倾向参与，但仍要看名字/内容特征
        if mod.kind == "module":
            lower_name = mod.name.lower()
            lower_path = mod.path.lower()
            if any(hint in lower_name or hint in lower_path for hint in ACTIONISH_KEYWORDS):
                return True

            for rel in mod.files:
                node = self.file_nodes.get(rel)
                if not node:
                    continue
                names = [*node.functions, *node.classes, *node.calls]
                if any(any(k in name.lower() for k in ACTIONISH_KEYWORDS) for name in names):
                    return True

        return False

    def _judge_dispatch(self, mod: ModuleRecord, hits: List[str]) -> str:
        if mod.name == "QuantumActionDispatcher":
            return "dispatcher_core"
        if hits:
            return "connected"

        if not self._is_action_layer_module(mod):
            return "not_applicable"

        return "bypassing_or_missing"

    def _judge_gui(self, mod: ModuleRecord, hits: List[str]) -> str:
        lower_path = mod.path.lower()
        lower_name = mod.name.lower()

        if "entry/gui_entry" in lower_path or lower_path.endswith("gui_main.py") or any(h in lower_name for h in GUI_LAYER_NAME_HINTS):
            return "gui_layer"

        return "direct_coupling" if hits else "not_connected"

    def _judge_reachability(self, mod: ModuleRecord, reach_hits: List[str]) -> str:
        if not mod.files:
            return "unknown"
        if len(reach_hits) == len(mod.files):
            return "reachable"
        if reach_hits:
            return "partially_reachable"
        return "not_reachable"

    def _append_module_issues(self, mod: ModuleRecord) -> None:
        if mod.kind == "module":
            if not mod.manifest.exists:
                mod.issues.append("缺少 manifest.json")
            if mod.manifest.missing_required:
                mod.issues.append(f"manifest 缺少必填字段: {', '.join(mod.manifest.missing_required)}")
            if mod.manifest.missing_recommended:
                mod.issues.append(f"manifest 缺少建议字段: {', '.join(mod.manifest.missing_recommended)}")
            mod.issues.extend(mod.manifest.issues)

        if mod.static_entry_reachability == "not_reachable":
            mod.issues.append("未从主入口链路静态触达")
        elif mod.static_entry_reachability == "partially_reachable":
            mod.issues.append("仅部分文件从主入口链路静态触达")

        if mod.dispatch_integration == "bypassing_or_missing":
            mod.issues.append("疑似未接入统一调度")
        if mod.gui_integration == "direct_coupling":
            mod.issues.append("模块内部存在 GUI import/调用级耦合证据")
        if mod.kind == "module" and not mod.depended_by:
            mod.issues.append("没有被其他模块静态依赖，可能是动态加载模块/边缘模块/死代码，需结合运行时确认")

    def _final_status(self, mod: ModuleRecord) -> str:
        if mod.score >= 60:
            return "critical"
        if mod.score >= 35:
            return "warning"
        if mod.score >= 15:
            return "needs_attention"
        return "healthy"

    # -------------------------
    # Helpers
    # -------------------------
    def _list_module_files(self, path: Path) -> List[str]:
        files = []
        for p in self._iter_dir_files(path):
            if p.suffix in TEXT_EXTENSIONS:
                files.append(self._rel(p))
        return sorted(files)

    def _iter_dir_files(self, path: Path) -> Iterable[Path]:
        for dirpath, dirnames, filenames in os.walk(path):
            current_dir = Path(dirpath)

            if self._should_skip_dirpath(current_dir):
                dirnames[:] = []
                continue

            dirnames[:] = [
                d for d in dirnames
                if d not in EXCLUDED_DIRS
                and not self._should_skip_dirpath(current_dir / d)
            ]

            for filename in filenames:
                yield current_dir / filename

    def _discover_entry_candidates(self, module_dir: Path, manifest: ManifestAudit) -> List[str]:
        candidates: List[str] = []

        if manifest.entry_declared and manifest.entry_exists:
            text = manifest.entry_declared
            if ":" in text:
                left = text.split(":", 1)[0]
                if left.endswith(".py"):
                    path = module_dir / left
                    if path.exists():
                        candidates.append(self._rel(path))
                else:
                    resolved = self._resolve_import_name_to_paths(left)
                    candidates.extend(sorted(resolved))
            else:
                if "/" in text or text.endswith(".py"):
                    path = module_dir / text
                    if path.exists():
                        candidates.append(self._rel(path))
                else:
                    resolved = self._resolve_import_name_to_paths(text)
                    candidates.extend(sorted(resolved))
                    if "." in text:
                        resolved2 = self._resolve_import_name_to_paths(text.rsplit(".", 1)[0])
                        candidates.extend(sorted(resolved2))

        common = [
            "main.py",
            "module.py",
            "bootstrap.py",
            "entry.py",
            "action.py",
            "service.py",
            "__init__.py",
        ]
        for filename in common:
            path = module_dir / filename
            if path.exists():
                candidates.append(self._rel(path))

        return sorted(dict.fromkeys(candidates))

    def _extract_manifest_dependencies(self, data: Dict[str, Any]) -> List[str]:
        if not isinstance(data, dict):
            return []
        dep_value = self._first_existing_key(data, ["dependencies", "deps", "requires"])
        if dep_value is None:
            return []
        if isinstance(dep_value, list):
            return [str(x) for x in dep_value]
        if isinstance(dep_value, dict):
            return [str(k) for k in dep_value.keys()]
        if isinstance(dep_value, str):
            return [dep_value]
        return []

    def _flatten_alias_pairs(self, data: Any, prefix: str = "") -> List[Tuple[str, Any]]:
        pairs: List[Tuple[str, Any]] = []
        if isinstance(data, dict):
            for key, value in data.items():
                full_key = f"{prefix}.{key}" if prefix else str(key)
                if isinstance(value, (dict, list)):
                    pairs.extend(self._flatten_alias_pairs(value, full_key))
                else:
                    pairs.append((full_key, value))
        elif isinstance(data, list):
            for idx, value in enumerate(data):
                full_key = f"{prefix}[{idx}]"
                if isinstance(value, (dict, list)):
                    pairs.extend(self._flatten_alias_pairs(value, full_key))
                else:
                    pairs.append((full_key, value))
        return pairs

    def _file_uses_dispatch(self, node: FileNode) -> bool:
        joined = " ".join(
            list(node.imports)
            + list(node.from_imports)
            + list(node.calls)
            + node.functions
            + node.classes
        ).lower()
        return any(k.lower() in joined for k in DISPATCH_KEYWORDS)

    def _file_uses_gui(self, node: FileNode) -> bool:
        # v2.2: 不再用字符串常量当证据，避免误报
        joined = " ".join(
            list(node.imports)
            + list(node.from_imports)
            + list(node.calls)
        ).lower()
        return any(k.lower() in joined for k in GUI_IMPORT_KEYWORDS)

    def _resolve_import_name_to_paths(self, imported_name: str) -> Set[str]:
        results: Set[str] = set()
        if imported_name in self.module_name_to_paths:
            results.update(self.module_name_to_paths[imported_name])

        parts = imported_name.split(".")
        while parts:
            candidate = ".".join(parts)
            if candidate in self.module_name_to_paths:
                results.update(self.module_name_to_paths[candidate])
            init_candidate = f"{candidate}.__init__"
            if init_candidate in self.module_name_to_paths:
                results.update(self.module_name_to_paths[init_candidate])
            parts.pop()
        return results

    def _resolve_relative_import(self, current_module_name: str, module: str, level: int) -> str:
        if level <= 0:
            return module

        base_parts = current_module_name.split(".")
        if base_parts[-1] == "__init__":
            base_parts = base_parts[:-1]
        else:
            base_parts = base_parts[:-1]

        ascend = max(level - 1, 0)
        if ascend > len(base_parts):
            prefix_parts: List[str] = []
        else:
            prefix_parts = base_parts[: len(base_parts) - ascend]

        prefix = ".".join(prefix_parts)
        if prefix and module:
            return f"{prefix}.{module}"
        return prefix or module

    def _get_call_name(self, func: ast.AST) -> Optional[str]:
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            parts: List[str] = []
            current: Optional[ast.AST] = func
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            parts.reverse()
            return ".".join(parts)
        return None

    def _path_to_import_name(self, rel: str) -> str:
        no_suffix = rel[:-3] if rel.endswith(".py") else rel
        return no_suffix.replace("/", ".")

    def _first_existing_key(self, data: Dict[str, Any], keys: List[str]) -> Any:
        for key in keys:
            if key in data:
                return data[key]
        return None

    def _alias_count(self) -> int:
        if isinstance(self.alias_map, list):
            return len(self.alias_map)
        if isinstance(self.alias_map, dict):
            return len(self.alias_map)
        return 0

    def _alias_schema_name(self) -> str:
        if isinstance(self.alias_map, list):
            return "list"
        if isinstance(self.alias_map, dict):
            return "dict"
        return type(self.alias_map).__name__

    def _module_to_dict(self, mod: ModuleRecord) -> Dict[str, Any]:
        result = asdict(mod)
        result["manifest"] = asdict(mod.manifest)
        return result

    def _sorted_modules(self) -> List[ModuleRecord]:
        return sorted(
            self.module_records.values(),
            key=lambda m: (m.score, m.kind == "module", m.name),
            reverse=True,
        )

    def _write_json(self, payload: Dict[str, Any]) -> None:
        out = self.output_dir / "system_audit.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_markdown(self, payload: Dict[str, Any]) -> None:
        out = self.output_dir / "system_audit.md"
        lines: List[str] = []
        summary = payload["summary"]

        lines.append("# 三花聚顶系统 · 静态结构与模块关系审计报告 v2.2")
        lines.append("")
        lines.append(f"- 项目根目录：`{summary['project_root']}`")
        lines.append(f"- Python 文件数：`{summary['total_python_files']}`")
        lines.append(f"- modules/ 与 模块/ 总模块数：`{summary['total_modules']}`")
        lines.append(f"- 核心组件数：`{summary['total_core_components']}`")
        lines.append(f"- 主入口种子：`{', '.join(summary['entry_seeds']) or '未发现'}`")
        lines.append("")

        lines.append("## 最值得优先修复的 3 个 blocker")
        lines.append("")
        if summary["blockers"]:
            for idx, blocker in enumerate(summary["blockers"], start=1):
                lines.append(f"### {idx}. {blocker['title']} [{blocker['severity']}]")
                lines.append(f"- 原因：{blocker['why']}")
                if blocker.get("affected_modules"):
                    lines.append(f"- 影响模块：{', '.join(blocker['affected_modules'])}")
                if blocker.get("evidence"):
                    lines.append(f"- 证据：{'; '.join(blocker['evidence'])}")
                lines.append(f"- 建议：{blocker['recommendation']}")
                lines.append("")
        else:
            lines.append("未发现 blocker。")
            lines.append("")

        lines.append("## 模块总表")
        lines.append("")
        lines.append("| 模块 | 类型 | 状态 | manifest | 调度接入 | GUI接入 | 静态入口可达性 | 评分 |")
        lines.append("|---|---|---|---|---|---|---|---:|")
        for mod in self._sorted_modules():
            manifest_flag = "OK" if mod.manifest.exists and not mod.manifest.missing_required else "BAD"
            lines.append(
                f"| {mod.name} | {mod.kind} | {mod.status} | {manifest_flag} | {mod.dispatch_integration} | {mod.gui_integration} | {mod.static_entry_reachability} | {mod.score} |"
            )
        lines.append("")

        lines.append("## 模块详情")
        lines.append("")
        for mod in self._sorted_modules():
            lines.append(f"### {mod.name}")
            lines.append(f"- 类型：`{mod.kind}`")
            lines.append(f"- 路径：`{mod.path}`")
            if mod.root_group:
                lines.append(f"- 来源分组：`{mod.root_group}`")
            lines.append(f"- 状态：`{mod.status}`")
            lines.append(f"- 入口候选：`{', '.join(mod.entry_candidates) or '无'}`")
            lines.append(f"- manifest：`{'存在' if mod.manifest.exists else '缺失'}`")
            if mod.manifest.missing_required:
                lines.append(f"- manifest 缺少必填：`{', '.join(mod.manifest.missing_required)}`")
            if mod.manifest.missing_recommended:
                lines.append(f"- manifest 缺少建议：`{', '.join(mod.manifest.missing_recommended)}`")
            if mod.manifest.entry_declared:
                lines.append(
                    f"- manifest.entry：`{mod.manifest.entry_declared}` / 解析类型：`{mod.manifest.entry_kind}` / 存在：`{mod.manifest.entry_exists}`"
                )
            lines.append(f"- 声明依赖：`{', '.join(mod.declared_dependencies) or '无'}`")
            lines.append(f"- 静态依赖：`{', '.join(mod.static_dependencies) or '无'}`")
            lines.append(f"- 被依赖：`{', '.join(mod.depended_by) or '无'}`")
            lines.append(f"- 调度接入：`{mod.dispatch_integration}`")
            lines.append(f"- GUI 接入：`{mod.gui_integration}`")
            lines.append(f"- 静态入口可达性：`{mod.static_entry_reachability}`")
            lines.append(f"- alias 展示词：`{', '.join(mod.aliases) or '无'}`")
            lines.append(f"- alias 函数：`{', '.join(mod.alias_functions) or '无'}`")

            if mod.issues:
                lines.append("- 问题：")
                for issue in mod.issues:
                    lines.append(f"  - {issue}")
            if mod.evidence.get("dispatch_hits"):
                lines.append(f"- 调度证据：`{', '.join(mod.evidence['dispatch_hits'])}`")
            if mod.evidence.get("gui_hits"):
                lines.append(f"- GUI 证据：`{', '.join(mod.evidence['gui_hits'])}`")
            if mod.evidence.get("static_reachable_files"):
                lines.append(f"- 静态可达文件：`{', '.join(mod.evidence['static_reachable_files'])}`")
            lines.append("")

        if payload.get("syntax_errors"):
            lines.append("## 语法错误")
            lines.append("")
            for item in payload["syntax_errors"]:
                lines.append(f"- `{item['path']}`: {item['error']}")
            lines.append("")

        alias_info = payload.get("aliases", {})
        lines.append("## aliases 审计")
        lines.append("")
        lines.append(f"- 文件：`{alias_info.get('path') or '缺失'}`")
        lines.append(f"- schema：`{alias_info.get('schema')}`")
        lines.append(f"- 数量：`{alias_info.get('count', 0)}`")
        if alias_info.get("issues"):
            lines.append("- 问题：")
            for issue in alias_info["issues"]:
                lines.append(f"  - {issue}")
        else:
            lines.append("- 问题：无")
        lines.append("")

        out.write_text("\n".join(lines), encoding="utf-8")

    def _write_graphviz(self, payload: Dict[str, Any]) -> None:
        out = self.output_dir / "system_audit.dot"
        lines = ["digraph system_audit {", "  rankdir=LR;", '  node [shape=box, fontsize=10];']
        for mod in self._sorted_modules():
            color = {
                "critical": "red",
                "warning": "orange",
                "needs_attention": "gold",
                "healthy": "green",
            }.get(mod.status, "gray")
            lines.append(f'  "{mod.name}" [color="{color}", label="{mod.name}\\n{mod.kind}\\n{mod.status}"];')
        for mod in self._sorted_modules():
            for dep in mod.static_dependencies:
                if dep in self.module_records:
                    lines.append(f'  "{mod.name}" -> "{dep}";')
        out.write_text("\n".join(lines + ["}"]), encoding="utf-8")

    def _rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def _relative_or_none(self, path: Path) -> Optional[str]:
        try:
            return self._rel(path)
        except Exception:
            return None


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="三花聚顶系统 · 静态结构与模块关系审计脚本 v2.2")
    parser.add_argument("--root", default=".", help="项目根目录，默认当前目录")
    parser.add_argument("--output-dir", default="./_audit", help="输出目录，默认 ./_audit")
    parser.add_argument(
        "--required-manifest-fields",
        default=",".join(DEFAULT_REQUIRED_MANIFEST_FIELDS),
        help="manifest 必填字段，逗号分隔",
    )
    parser.add_argument(
        "--recommended-manifest-fields",
        default=",".join(DEFAULT_RECOMMENDED_MANIFEST_FIELDS),
        help="manifest 建议字段，逗号分隔",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not root.exists():
        print(f"[ERROR] root 不存在: {root}", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"[ERROR] root 不是目录: {root}", file=sys.stderr)
        return 2

    required = [x.strip() for x in str(args.required_manifest_fields).split(",") if x.strip()]
    recommended = [x.strip() for x in str(args.recommended_manifest_fields).split(",") if x.strip()]

    auditor = ProjectAuditor(
        root=root,
        output_dir=output_dir,
        required_manifest_fields=required,
        recommended_manifest_fields=recommended,
    )
    payload = auditor.run()

    summary = payload["summary"]
    print("[OK] 静态审计完成")
    print(f"  项目根目录: {summary['project_root']}")
    print(f"  Python 文件数: {summary['total_python_files']}")
    print(f"  modules/ 与 模块/ 总模块数: {summary['total_modules']}")
    print(f"  核心组件数: {summary['total_core_components']}")
    print(f"  输出目录: {output_dir}")
    print("  输出文件:")
    print(f"    - {output_dir / 'system_audit.json'}")
    print(f"    - {output_dir / 'system_audit.md'}")
    print(f"    - {output_dir / 'system_audit.dot'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
