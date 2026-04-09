#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
三花聚顶系统全量体检脚本（修复版）
==================================================
功能：
1. 扫描项目内 Python 文件、manifest.json、入口文件
2. 提取模块、类、函数、导入关系
3. 分析 action 注册 / action 调用
4. 分析 event 发布 / 订阅
5. 检查 manifest 与代码的一致性
6. 生成 Markdown / JSON / CSV / DOT 报告

修复点：
- 修复 resolve()+relative_to() 在 symlink 场景下跳出项目根目录导致崩溃的问题
- 跳过指向项目外部的符号链接
- 路径归属判断改为词法路径，不跟随 symlink
- 增强异常容错，避免单个文件拖垮全局扫描

不依赖第三方库，仅使用 Python 标准库。
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# ============================================================
# 配置
# ============================================================

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    "audit_output",
    ".venv",
    "venv",
    "env",
    "site-packages",
    "_legacy_disabled",
}

PY_SUFFIX = ".py"
MANIFEST_NAME = "manifest.json"

ACTION_REGISTER_NAMES = {
    "register_action",
    "register_actions",
    "add_action",
    "register",
    "register_aliases",
}
ACTION_CALL_NAMES = {
    "dispatch_action",
    "call_action",
    "match_action",
    "execute_action",
    "run_action",
}
EVENT_PUBLISH_NAMES = {
    "publish",
    "emit",
    "broadcast",
    "dispatch_event",
    "notify",
}
EVENT_SUBSCRIBE_NAMES = {
    "subscribe",
    "on",
    "listen",
    "register_handler",
    "register_listener",
}

ENTRY_HINT_FILES = {
    "gui_main.py",
    "cli_entry.py",
    "aicore.py",
    "action_dispatcher.py",
    "module.py",
    "module_manager.py",
    "manager.py",
}

BASEMODULE_CANDIDATE_WHITELIST = {
    "music_module",
    "state_describe",
}

LAYER_RULES = {
    "entry": ["core", "modules", "config", "assets", "models"],
    "core": ["core", "modules", "config", "assets", "models"],
    "modules": ["core", "modules", "config", "assets", "models"],
    "config": [],
    "assets": [],
    "models": [],
}


# ============================================================
# 数据结构
# ============================================================

@dataclass
class FileInfo:
    path: str
    rel_path: str
    module_path: str
    file_hash: str
    line_count: int
    size_bytes: int
    is_entry_hint: bool = False


@dataclass
class ClassInfo:
    name: str
    qualname: str
    file: str
    lineno: int
    bases: List[str] = field(default_factory=list)
    decorators: List[str] = field(default_factory=list)
    methods: List[str] = field(default_factory=list)
    is_base_module_candidate: bool = False


@dataclass
class FunctionInfo:
    name: str
    qualname: str
    file: str
    lineno: int
    decorators: List[str] = field(default_factory=list)


@dataclass
class ImportEdge:
    source_file: str
    source_module: str
    imported_module: str
    lineno: int
    kind: str
    internal: bool


@dataclass
class ActionEdge:
    source_file: str
    source_module: str
    action_name: str
    lineno: int
    kind: str  # register / call / alias / manifest_declared


@dataclass
class EventEdge:
    source_file: str
    source_module: str
    event_name: str
    lineno: int
    kind: str  # publish / subscribe / manifest_declared


@dataclass
class ManifestInfo:
    manifest_path: str
    module_dir: str
    data: Dict[str, Any]
    module_name: Optional[str] = None
    entry_class: Optional[str] = None
    entry: Optional[str] = None
    enabled: Optional[bool] = None
    actions: List[str] = field(default_factory=list)
    events: List[str] = field(default_factory=list)


@dataclass
class ModuleInfo:
    name: str
    directory: str
    manifest_path: Optional[str] = None
    entry_class: Optional[str] = None
    entry: Optional[str] = None
    enabled: Optional[bool] = None
    py_files: List[str] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)
    action_names: List[str] = field(default_factory=list)
    event_names: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)


@dataclass
class RiskItem:
    level: str   # HIGH / MEDIUM / LOW
    code: str
    message: str
    target: str


# ============================================================
# 工具函数
# ============================================================

def sha1_of_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 64)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def safe_read_text(path: Path) -> str:
    encodings = ["utf-8", "utf-8-sig", "gbk", "latin-1"]
    for enc in encodings:
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return path.read_text(errors="ignore")


def normalize_rel(path: Path, root: Path) -> str:
    """
    只做词法级相对路径计算，不跟随 symlink。
    避免项目内符号链接 resolve 后跳到项目外部导致 relative_to 报错。
    """
    try:
        rel = path.relative_to(root)
    except ValueError:
        return str(path).replace("\\", "/")
    return str(rel).replace("\\", "/")


def path_to_module(rel_path: str) -> str:
    if rel_path.endswith(".py"):
        rel_path = rel_path[:-3]
    parts = [p for p in rel_path.split("/") if p and p != "__init__"]
    return ".".join(parts)


def detect_layer(rel_path: str) -> str:
    p = rel_path.replace("\\", "/")
    if p.startswith("entry/"):
        return "entry"
    if p.startswith("core/"):
        return "core"
    if p.startswith("modules/") or p.startswith("模块/"):
        return "modules"
    if p.startswith("config/"):
        return "config"
    if p.startswith("assets/"):
        return "assets"
    if p.startswith("models/"):
        return "models"
    return "other"


def ensure_output_dir(root: Path) -> Path:
    out = root / "audit_output"
    out.mkdir(parents=True, exist_ok=True)
    return out


def csv_write(path: Path, headers: List[str], rows: List[List[Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


def is_excluded(path: Path, root: Path, exclude_dirs: Set[str]) -> bool:
    """
    不跟随 symlink，只按当前项目树中的词法路径判断是否排除。
    """
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        return True
    return any(part in exclude_dirs for part in rel_parts)


def is_external_symlink(path: Path, root: Path) -> bool:
    """
    如果当前文件是符号链接，且真实目标不在项目根目录内，则跳过。
    避免把系统 Python、外部依赖、别的磁盘文件误扫进来。
    """
    if not path.is_symlink():
        return False

    try:
        target = path.resolve(strict=False)
        target.relative_to(root)
        return False
    except ValueError:
        return True
    except Exception:
        return False


def dotted_prefix_match(mod: str, candidates: Set[str]) -> bool:
    if mod in candidates:
        return True
    for c in candidates:
        if mod.startswith(c + "."):
            return True
    return False


def extract_str(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.strip()
    if isinstance(node, ast.Str):
        return node.s.strip()
    return None


def extract_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = extract_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return extract_name(node.func)
    return None


def get_call_name(call: ast.Call) -> Optional[str]:
    return extract_name(call.func)


def node_to_source_fallback(text: str, node: ast.AST) -> str:
    try:
        segment = ast.get_source_segment(text, node)
        if segment:
            return segment.strip()
    except Exception:
        pass
    return ""


def infer_module_name_from_dir(dir_path: Path) -> str:
    return dir_path.name


def is_module_tree_path(rel_path: str) -> bool:
    rel_path = rel_path.replace("\\", "/")
    return rel_path.startswith("modules/") or rel_path.startswith("模块/")

def split_module_relpath(rel_path: str):
    """
    只接受真正的模块树路径：
    - modules/<mod_name>/...
    - 模块/<mod_name>/...
    返回: (tree_root, module_name, inner_rel)
    非法则返回 None
    """
    rel_path = rel_path.replace("\\", "/")
    parts = [p for p in rel_path.split("/") if p]

    # 至少应为 modules/<module>/<file>
    if len(parts) < 3:
        return None

    if parts[0] not in {"modules", "模块"}:
        return None

    module_name = parts[1]

    # 排除 modules/__init__.py / 模块/__init__.py 这种根文件误判
    if module_name.endswith(".py"):
        return None

    inner_rel = "/".join(parts[2:])
    return parts[0], module_name, inner_rel


# ============================================================
# AST 扫描器
# ============================================================

class FileAnalyzer(ast.NodeVisitor):
    def __init__(self, text: str, file_info: FileInfo, internal_modules: Set[str]):
        self.text = text
        self.file_info = file_info
        self.internal_modules = internal_modules

        self.classes: List[ClassInfo] = []
        self.functions: List[FunctionInfo] = []
        self.imports: List[ImportEdge] = []
        self.actions: List[ActionEdge] = []
        self.events: List[EventEdge] = []

        self._class_stack: List[str] = []
        self._func_stack: List[str] = []

    def current_qual_prefix(self) -> str:
        parts = self._class_stack + self._func_stack
        return ".".join(parts) if parts else ""

    def qualify(self, name: str) -> str:
        prefix = self.current_qual_prefix()
        return f"{prefix}.{name}" if prefix else name

    def visit_Import(self, node: ast.Import) -> Any:
        for alias in node.names:
            mod = alias.name
            internal = dotted_prefix_match(mod, self.internal_modules)
            self.imports.append(
                ImportEdge(
                    source_file=self.file_info.rel_path,
                    source_module=self.file_info.module_path,
                    imported_module=mod,
                    lineno=node.lineno,
                    kind="import",
                    internal=internal,
                )
            )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        mod = node.module or ""

        if node.level and self.file_info.module_path:
            base_parts = self.file_info.module_path.split(".")
            curr_parts = base_parts[:-1] if base_parts else []
            if node.level <= len(curr_parts) + 1:
                if node.level > 1:
                    prefix = curr_parts[:-(node.level - 1)] if (node.level - 1) <= len(curr_parts) else []
                else:
                    prefix = curr_parts
                rel_mod = ".".join(prefix + ([mod] if mod else []))
            else:
                rel_mod = mod
            mod = rel_mod

        internal = dotted_prefix_match(mod, self.internal_modules)
        self.imports.append(
            ImportEdge(
                source_file=self.file_info.rel_path,
                source_module=self.file_info.module_path,
                imported_module=mod,
                lineno=node.lineno,
                kind="from-import",
                internal=internal,
            )
        )
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        bases = [extract_name(b) or node_to_source_fallback(self.text, b) for b in node.bases]
        decorators = [extract_name(d) or node_to_source_fallback(self.text, d) for d in node.decorator_list]
        qual = self.qualify(node.name)

        info = ClassInfo(
            name=node.name,
            qualname=qual,
            file=self.file_info.rel_path,
            lineno=node.lineno,
            bases=bases,
            decorators=decorators,
            methods=[],
            is_base_module_candidate=(
                any("BaseModule" in b for b in bases) or node.name.endswith("Module")
            ),
        )
        self.classes.append(info)

        self._class_stack.append(node.name)
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                info.methods.append(item.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        decorators = [extract_name(d) or node_to_source_fallback(self.text, d) for d in node.decorator_list]
        qual = self.qualify(node.name)
        self.functions.append(
            FunctionInfo(
                name=node.name,
                qualname=qual,
                file=self.file_info.rel_path,
                lineno=node.lineno,
                decorators=decorators,
            )
        )
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self.visit_FunctionDef(node)

    def visit_Call(self, node: ast.Call) -> Any:
        call_name = get_call_name(node)
        if call_name:
            tail = call_name.split(".")[-1]

            if tail in ACTION_REGISTER_NAMES:
                action_name = self._extract_action_name_from_call(node)
                if action_name:
                    self.actions.append(
                        ActionEdge(
                            source_file=self.file_info.rel_path,
                            source_module=self.file_info.module_path,
                            action_name=action_name,
                            lineno=node.lineno,
                            kind="register",
                        )
                    )

            elif tail in ACTION_CALL_NAMES:
                action_name = self._extract_action_name_from_call(node)
                if action_name:
                    self.actions.append(
                        ActionEdge(
                            source_file=self.file_info.rel_path,
                            source_module=self.file_info.module_path,
                            action_name=action_name,
                            lineno=node.lineno,
                            kind="call",
                        )
                    )

            if tail in EVENT_PUBLISH_NAMES:
                event_name = self._extract_event_name_from_call(node)
                if event_name:
                    self.events.append(
                        EventEdge(
                            source_file=self.file_info.rel_path,
                            source_module=self.file_info.module_path,
                            event_name=event_name,
                            lineno=node.lineno,
                            kind="publish",
                        )
                    )

            elif tail in EVENT_SUBSCRIBE_NAMES:
                event_name = self._extract_event_name_from_call(node)
                if event_name:
                    self.events.append(
                        EventEdge(
                            source_file=self.file_info.rel_path,
                            source_module=self.file_info.module_path,
                            event_name=event_name,
                            lineno=node.lineno,
                            kind="subscribe",
                        )
                    )

        self.generic_visit(node)

    def _extract_action_name_from_call(self, node: ast.Call) -> Optional[str]:
        for arg in node.args[:3]:
            s = extract_str(arg)
            if s:
                return s
        for kw in node.keywords:
            if kw.arg in {"name", "action", "action_name"}:
                s = extract_str(kw.value)
                if s:
                    return s
        return None

    def _extract_event_name_from_call(self, node: ast.Call) -> Optional[str]:
        for arg in node.args[:3]:
            s = extract_str(arg)
            if s:
                return s
        for kw in node.keywords:
            if kw.arg in {"name", "event", "event_name", "topic"}:
                s = extract_str(kw.value)
                if s:
                    return s
        return None


# ============================================================
# 核心分析器
# ============================================================

class SanhuaSystemAuditor:
    def __init__(self, root: Path, exclude_dirs: Optional[Set[str]] = None):
        self.root = root.resolve()
        self.exclude_dirs = exclude_dirs or set(DEFAULT_EXCLUDE_DIRS)
        self.out_dir = ensure_output_dir(self.root)

        self.file_infos: Dict[str, FileInfo] = {}
        self.class_infos: List[ClassInfo] = []
        self.function_infos: List[FunctionInfo] = []
        self.import_edges: List[ImportEdge] = []
        self.action_edges: List[ActionEdge] = []
        self.event_edges: List[EventEdge] = []
        self.manifests: List[ManifestInfo] = []
        self.modules: Dict[str, ModuleInfo] = {}
        self.risks: List[RiskItem] = []
        self.syntax_errors: List[Dict[str, Any]] = []

        self.internal_modules: Set[str] = set()

    # ------------------------
    # 运行总入口
    # ------------------------

    def run(self) -> Dict[str, Any]:
        self.scan_files()
        self.build_internal_module_index()
        self.analyze_python_files()
        self.analyze_manifests()
        self.build_modules()
        self.check_manifest_consistency()
        self.check_architecture_rules()
        self.check_cycles()
        self.write_outputs()
        return self.build_report_dict()

    # ------------------------
    # 文件扫描
    # ------------------------

    def scan_files(self) -> None:
        for path in self.root.rglob("*"):
            try:
                if not path.is_file():
                    continue
            except Exception:
                continue

            # 跳过指向项目外部的符号链接
            if is_external_symlink(path, self.root):
                self.risks.append(
                    RiskItem(
                        level="LOW",
                        code="SKIP_EXTERNAL_SYMLINK",
                        message="跳过指向项目外部的符号链接，避免污染扫描结果",
                        target=normalize_rel(path, self.root),
                    )
                )
                continue

            if is_excluded(path, self.root, self.exclude_dirs):
                continue

            rel = normalize_rel(path, self.root)

            if path.suffix == PY_SUFFIX:
                try:
                    text = safe_read_text(path)
                    fi = FileInfo(
                        path=str(path),
                        rel_path=rel,
                        module_path=path_to_module(rel),
                        file_hash=sha1_of_file(path),
                        line_count=text.count("\n") + 1 if text else 0,
                        size_bytes=path.stat().st_size,
                        is_entry_hint=(path.name in ENTRY_HINT_FILES),
                    )
                    self.file_infos[rel] = fi
                except Exception as e:
                    self.risks.append(
                        RiskItem(
                            level="MEDIUM",
                            code="PY_SCAN_ERROR",
                            message=f"扫描 Python 文件失败：{e}",
                            target=rel,
                        )
                    )

            elif path.name == MANIFEST_NAME:
                # manifest 后续统一解析
                pass

    def build_internal_module_index(self) -> None:
        for fi in self.file_infos.values():
            if fi.module_path:
                self.internal_modules.add(fi.module_path)

        top_levels = set()
        for fi in self.file_infos.values():
            if fi.module_path:
                top_levels.add(fi.module_path.split(".")[0])
        self.internal_modules.update(top_levels)

    # ------------------------
    # Python AST 分析
    # ------------------------

    def analyze_python_files(self) -> None:
        for rel, fi in self.file_infos.items():
            path = self.root / rel
            try:
                text = safe_read_text(path)
            except Exception as e:
                self.risks.append(
                    RiskItem(
                        level="MEDIUM",
                        code="READ_FILE_ERROR",
                        message=f"读取文件失败：{e}",
                        target=rel,
                    )
                )
                continue

            try:
                tree = ast.parse(text, filename=rel)
            except SyntaxError as e:
                self.syntax_errors.append(
                    {
                        "file": rel,
                        "line": e.lineno,
                        "offset": e.offset,
                        "msg": e.msg,
                    }
                )
                self.risks.append(
                    RiskItem(
                        level="HIGH",
                        code="SYNTAX_ERROR",
                        message=f"语法错误：{e.msg} (line {e.lineno})",
                        target=rel,
                    )
                )
                continue
            except Exception as e:
                self.risks.append(
                    RiskItem(
                        level="MEDIUM",
                        code="AST_PARSE_ERROR",
                        message=f"AST 解析失败：{e}",
                        target=rel,
                    )
                )
                continue

            analyzer = FileAnalyzer(text, fi, self.internal_modules)
            try:
                analyzer.visit(tree)
            except Exception as e:
                self.risks.append(
                    RiskItem(
                        level="MEDIUM",
                        code="AST_VISIT_ERROR",
                        message=f"AST 遍历失败：{e}",
                        target=rel,
                    )
                )
                continue

            self.class_infos.extend(analyzer.classes)
            self.function_infos.extend(analyzer.functions)
            self.import_edges.extend(analyzer.imports)
            self.action_edges.extend(analyzer.actions)
            self.event_edges.extend(analyzer.events)

    # ------------------------
    # Manifest 分析
    # ------------------------

    def analyze_manifests(self) -> None:
        for path in self.root.rglob(MANIFEST_NAME):
            try:
                if not path.is_file():
                    continue
            except Exception:
                continue

            if is_external_symlink(path, self.root):
                self.risks.append(
                    RiskItem(
                        level="LOW",
                        code="SKIP_EXTERNAL_SYMLINK",
                        message="跳过指向项目外部的 manifest 符号链接",
                        target=normalize_rel(path, self.root),
                    )
                )
                continue

            if is_excluded(path, self.root, self.exclude_dirs):
                continue

            try:
                data = json.loads(safe_read_text(path))
            except Exception as e:
                self.risks.append(
                    RiskItem(
                        level="HIGH",
                        code="MANIFEST_JSON_ERROR",
                        message=f"manifest.json 解析失败：{e}",
                        target=normalize_rel(path, self.root),
                    )
                )
                continue

            actions: List[str] = []
            events: List[str] = []

            if isinstance(data.get("actions"), list):
                for a in data["actions"]:
                    if isinstance(a, dict):
                        name = a.get("name")
                        if isinstance(name, str) and name.strip():
                            actions.append(name.strip())

            if isinstance(data.get("events"), list):
                for e in data["events"]:
                    if isinstance(e, dict):
                        name = e.get("name")
                        if isinstance(name, str) and name.strip():
                            events.append(name.strip())

            mi = ManifestInfo(
                manifest_path=normalize_rel(path, self.root),
                module_dir=normalize_rel(path.parent, self.root),
                data=data,
                module_name=data.get("name"),
                entry_class=data.get("entry_class"),
                entry=data.get("entry"),
                enabled=data.get("enabled"),
                actions=actions,
                events=events,
            )
            self.manifests.append(mi)

            mod_path = path_to_module(normalize_rel(path.parent, self.root))
            for a in actions:
                self.action_edges.append(
                    ActionEdge(
                        source_file=mi.manifest_path,
                        source_module=mod_path,
                        action_name=a,
                        lineno=0,
                        kind="manifest_declared",
                    )
                )
            for e in events:
                self.event_edges.append(
                    EventEdge(
                        source_file=mi.manifest_path,
                        source_module=mod_path,
                        event_name=e,
                        lineno=0,
                        kind="manifest_declared",
                    )
                )

    # ------------------------
    # 模块聚合
    # ------------------------

    def build_modules(self) -> None:
        modules_dir = self.root / "modules"
        if modules_dir.exists():
            for child in modules_dir.iterdir():
                if child.is_dir():
                    name = child.name
                    self.modules[name] = ModuleInfo(
                        name=name,
                        directory=normalize_rel(child, self.root),
                    )

        for m in self.manifests:
            parsed = split_module_relpath(m.module_dir)
            if parsed:
                tree_root, module_name, inner_rel = parsed
                directory = f"{tree_root}/{module_name}"
            else:
                # 非真正模块树的目录里，models/ 只视为资源，不纳入模块治理
                if m.module_dir.replace("\\", "/").startswith("models/"):
                    continue
                module_name = m.module_name or infer_module_name_from_dir(self.root / m.module_dir)
                directory = m.module_dir

            if module_name not in self.modules:
                self.modules[module_name] = ModuleInfo(
                    name=module_name,
                    directory=directory,
                )
            mod = self.modules[module_name]
            mod.manifest_path = m.manifest_path
            mod.entry_class = m.entry_class
            mod.entry = m.entry
            mod.enabled = m.enabled
            mod.action_names.extend([a for a in m.actions if a not in mod.action_names])
            mod.event_names.extend([e for e in m.events if e not in mod.event_names])

        for rel, fi in self.file_infos.items():
            parsed = split_module_relpath(rel)
            if not parsed:
                continue

            tree_root, mod_name, inner_rel = parsed
            directory = f"{tree_root}/{mod_name}"

            if mod_name not in self.modules:
                self.modules[mod_name] = ModuleInfo(
                    name=mod_name,
                    directory=directory,
                )

            self.modules[mod_name].py_files.append(rel)

        for ci in self.class_infos:
            parsed = split_module_relpath(ci.file)
            if not parsed:
                continue

            tree_root, mod_name, inner_rel = parsed
            directory = f"{tree_root}/{mod_name}"

            if mod_name not in self.modules:
                self.modules[mod_name] = ModuleInfo(
                    name=mod_name,
                    directory=directory,
                )

            self.modules[mod_name].classes.append(ci.qualname)

        for ae in self.action_edges:
            parsed = split_module_relpath(ae.source_file)
            if not parsed:
                continue

            _, mod_name, _ = parsed
            if mod_name in self.modules and ae.action_name not in self.modules[mod_name].action_names:
                self.modules[mod_name].action_names.append(ae.action_name)

        for ee in self.event_edges:
            parsed = split_module_relpath(ee.source_file)
            if not parsed:
                continue

            _, mod_name, _ = parsed
            if mod_name in self.modules and ee.event_name not in self.modules[mod_name].event_names:
                self.modules[mod_name].event_names.append(ee.event_name)

        for mod in self.modules.values():
            if (mod.directory.startswith("modules/") or mod.directory.startswith("模块/")) and not mod.manifest_path:
                mod.issues.append("缺少 manifest.json")
                self.risks.append(
                    RiskItem(
                        level="HIGH",
                        code="MODULE_NO_MANIFEST",
                        message="模块目录存在，但缺少 manifest.json",
                        target=mod.directory,
                    )
                )

            # models/ 是资源目录，不按代码模块要求 Python 文件
            if mod.directory.startswith("models/"):
                continue

            if not mod.py_files:
                mod.issues.append("模块目录下无 Python 代码文件")
                self.risks.append(
                    RiskItem(
                        level="MEDIUM",
                        code="MODULE_NO_PY_FILES",
                        message="模块目录存在，但未发现 Python 文件",
                        target=mod.directory,
                    )
                )

    # ------------------------
    # 一致性检查
    # ------------------------

    def check_manifest_consistency(self) -> None:
        class_map = {ci.qualname: ci for ci in self.class_infos}
        short_class_map: Dict[str, List[ClassInfo]] = defaultdict(list)
        for ci in self.class_infos:
            short_class_map[ci.name].append(ci)

        for mod_name, mod in self.modules.items():
            if mod.manifest_path:
                dir_name = Path(mod.directory).name

                if mod_name != dir_name:
                    msg = f"manifest.name={mod_name} 与目录名={dir_name} 不一致"
                    mod.issues.append(msg)
                    self.risks.append(
                        RiskItem(
                            level="HIGH",
                            code="MANIFEST_NAME_MISMATCH",
                            message=msg,
                            target=mod.manifest_path,
                        )
                    )

                if mod.entry_class:
                    found = False
                    if mod.entry_class in class_map:
                        found = True
                    else:
                        short_name = mod.entry_class.split(".")[-1]
                        if short_name in short_class_map:
                            found = True

                    if not found:
                        msg = f"entry_class 未在代码中找到：{mod.entry_class}"
                        mod.issues.append(msg)
                        self.risks.append(
                            RiskItem(
                                level="HIGH",
                                code="ENTRY_CLASS_NOT_FOUND",
                                message=msg,
                                target=mod.manifest_path,
                            )
                        )

                declared = set(mod.action_names)
                code_actions = set()
                for ae in self.action_edges:
                    if ae.source_file.startswith(mod.directory + "/") and ae.kind in {"register", "manifest_declared"}:
                        code_actions.add(ae.action_name)

                missing = declared - code_actions
                for name in sorted(missing):
                    msg = f"manifest 声明的 action 未在代码注册痕迹中发现：{name}"
                    mod.issues.append(msg)
                    self.risks.append(
                        RiskItem(
                            level="MEDIUM",
                            code="ACTION_DECLARED_NOT_FOUND",
                            message=msg,
                            target=mod.manifest_path,
                        )
                    )

        for mod_name, mod in self.modules.items():
            if mod.directory.startswith("modules/") or mod.directory.startswith("模块/"):
                if mod_name in BASEMODULE_CANDIDATE_WHITELIST:
                    continue

                has_base_module = False
                for cls_name in mod.classes:
                    ci = next((x for x in self.class_infos if x.qualname == cls_name), None)
                    if ci and ci.is_base_module_candidate:
                        has_base_module = True
                        break

                if not has_base_module:
                    msg = "未发现明显的 BaseModule 子类或 *Module 命名类"
                    mod.issues.append(msg)
                    self.risks.append(
                        RiskItem(
                            level="MEDIUM",
                            code="NO_BASEMODULE_CANDIDATE",
                            message=msg,
                            target=mod.directory,
                        )
                    )

    # ------------------------
    # 架构规则检查
    # ------------------------

    def check_architecture_rules(self) -> None:
        for ie in self.import_edges:
            if not ie.internal:
                continue

            source_layer = detect_layer(ie.source_file)
            target_layer = detect_layer(ie.imported_module.replace(".", "/") + ".py")

            allowed = LAYER_RULES.get(source_layer, [])
            if target_layer == "other":
                continue

            if target_layer not in allowed and ie.imported_module:
                self.risks.append(
                    RiskItem(
                        level="LOW",
                        code="LAYER_CROSS_IMPORT",
                        message=f"疑似跨层引用：{source_layer} -> {target_layer}",
                        target=f"{ie.source_file}:{ie.lineno} => {ie.imported_module}",
                    )
                )

    # ------------------------
    # 循环依赖检查
    # ------------------------

    def check_cycles(self) -> None:
        graph: Dict[str, Set[str]] = defaultdict(set)
        for ie in self.import_edges:
            if ie.internal and ie.source_module and ie.imported_module:
                graph[ie.source_module].add(ie.imported_module)

        visited: Set[str] = set()
        stack: List[str] = []
        on_stack: Set[str] = set()
        cycles: List[List[str]] = []

        def dfs(node: str) -> None:
            visited.add(node)
            stack.append(node)
            on_stack.add(node)

            for nei in graph.get(node, set()):
                if nei not in visited:
                    dfs(nei)
                elif nei in on_stack:
                    try:
                        idx = stack.index(nei)
                        cycle = stack[idx:] + [nei]
                        cycles.append(cycle)
                    except ValueError:
                        pass

            stack.pop()
            on_stack.remove(node)

        for node in list(graph.keys()):
            if node not in visited:
                dfs(node)

        unique_cycles = []
        seen = set()
        for c in cycles:
            key = tuple(c)
            if key not in seen:
                seen.add(key)
                unique_cycles.append(c)

        for c in unique_cycles[:50]:
            # 过滤 A -> A 这类自循环误报
            if len(set(c)) <= 1:
                continue

            self.risks.append(
                RiskItem(
                    level="MEDIUM",
                    code="IMPORT_CYCLE",
                    message="疑似循环依赖：" + " -> ".join(c),
                    target=c[0],
                )
            )

    # ------------------------
    # 输出
    # ------------------------

    def build_report_dict(self) -> Dict[str, Any]:
        summary = {
            "root": str(self.root),
            "python_files": len(self.file_infos),
            "class_count": len(self.class_infos),
            "function_count": len(self.function_infos),
            "manifest_count": len(self.manifests),
            "module_count": len(self.modules),
            "import_edge_count": len(self.import_edges),
            "action_edge_count": len(self.action_edges),
            "event_edge_count": len(self.event_edges),
            "syntax_error_count": len(self.syntax_errors),
            "risk_count": len(self.risks),
        }

        risk_stats: Dict[str, int] = defaultdict(int)
        for r in self.risks:
            risk_stats[r.level] += 1

        modules = {}
        for k, v in sorted(self.modules.items()):
            modules[k] = asdict(v)

        return {
            "summary": summary,
            "risk_stats": dict(risk_stats),
            "syntax_errors": self.syntax_errors,
            "risks": [asdict(r) for r in self.risks],
            "modules": modules,
            "files": [asdict(fi) for _, fi in sorted(self.file_infos.items())],
            "classes": [asdict(ci) for ci in self.class_infos],
            "functions": [asdict(fi) for fi in self.function_infos],
            "manifests": [asdict(mi) for mi in self.manifests],
            "imports": [asdict(ie) for ie in self.import_edges],
            "actions": [asdict(ae) for ae in self.action_edges],
            "events": [asdict(ee) for ee in self.event_edges],
        }

    def write_outputs(self) -> None:
        report = self.build_report_dict()

        json_path = self.out_dir / "system_report.json"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        csv_write(
            self.out_dir / "imports_edges.csv",
            ["source_file", "source_module", "imported_module", "lineno", "kind", "internal"],
            [[e.source_file, e.source_module, e.imported_module, e.lineno, e.kind, e.internal] for e in self.import_edges],
        )

        csv_write(
            self.out_dir / "action_edges.csv",
            ["source_file", "source_module", "action_name", "lineno", "kind"],
            [[e.source_file, e.source_module, e.action_name, e.lineno, e.kind] for e in self.action_edges],
        )

        csv_write(
            self.out_dir / "event_edges.csv",
            ["source_file", "source_module", "event_name", "lineno", "kind"],
            [[e.source_file, e.source_module, e.event_name, e.lineno, e.kind] for e in self.event_edges],
        )

        csv_write(
            self.out_dir / "module_inventory.csv",
            ["name", "directory", "manifest_path", "entry_class", "entry", "enabled", "py_files", "classes", "actions", "events", "issues"],
            [[
                m.name,
                m.directory,
                m.manifest_path or "",
                m.entry_class or "",
                m.entry or "",
                m.enabled,
                "; ".join(sorted(m.py_files)),
                "; ".join(sorted(m.classes)),
                "; ".join(sorted(set(m.action_names))),
                "; ".join(sorted(set(m.event_names))),
                "; ".join(m.issues),
            ] for _, m in sorted(self.modules.items())],
        )

        self.write_dot()
        self.write_markdown(report)

    def file_to_module_bucket(self, rel_file: str) -> Optional[str]:
        if rel_file.startswith("modules/"):
            parts = rel_file.split("/")
            if len(parts) >= 2:
                return parts[1]
        if rel_file.startswith("core/"):
            return "core"
        if rel_file.startswith("entry/"):
            return "entry"
        return None

    def module_name_from_import(self, imported_module: str) -> Optional[str]:
        if not imported_module:
            return None
        parts = imported_module.split(".")
        if not parts:
            return None
        if parts[0] == "modules" and len(parts) >= 2:
            return parts[1]
        if parts[0] in {"core", "entry", "config", "assets"}:
            return parts[0]
        return None

    def write_dot(self) -> None:
        dot_lines = [
            'digraph SanhuaModuleGraph {',
            '  rankdir=LR;',
            '  node [shape=box, style=rounded];',
        ]

        mod_nodes = set()
        mod_edges = set()

        for ie in self.import_edges:
            src = self.file_to_module_bucket(ie.source_file)
            dst = self.module_name_from_import(ie.imported_module)
            if not src or not dst or src == dst:
                continue
            mod_nodes.add(src)
            mod_nodes.add(dst)
            mod_edges.add((src, dst, "import"))

        for name in self.modules.keys():
            mod_nodes.add(name)

        for n in sorted(mod_nodes):
            dot_lines.append(f'  "{n}";')

        for src, dst, kind in sorted(mod_edges):
            dot_lines.append(f'  "{src}" -> "{dst}" [label="{kind}"];')

        dot_lines.append("}")
        (self.out_dir / "module_graph.dot").write_text("\n".join(dot_lines), encoding="utf-8")

    def write_markdown(self, report: Dict[str, Any]) -> None:
        s = report["summary"]
        risk_stats = report["risk_stats"]

        lines: List[str] = []
        lines.append("# 三花聚顶系统体检报告")
        lines.append("")
        lines.append(f"- 根目录：`{s['root']}`")
        lines.append(f"- Python 文件数：**{s['python_files']}**")
        lines.append(f"- 类数量：**{s['class_count']}**")
        lines.append(f"- 函数数量：**{s['function_count']}**")
        lines.append(f"- manifest 数量：**{s['manifest_count']}**")
        lines.append(f"- 模块数量：**{s['module_count']}**")
        lines.append(f"- import 依赖边：**{s['import_edge_count']}**")
        lines.append(f"- action 边：**{s['action_edge_count']}**")
        lines.append(f"- event 边：**{s['event_edge_count']}**")
        lines.append(f"- 语法错误数：**{s['syntax_error_count']}**")
        lines.append(f"- 风险总数：**{s['risk_count']}**")
        lines.append("")

        lines.append("## 风险等级统计")
        lines.append("")
        lines.append(f"- HIGH：**{risk_stats.get('HIGH', 0)}**")
        lines.append(f"- MEDIUM：**{risk_stats.get('MEDIUM', 0)}**")
        lines.append(f"- LOW：**{risk_stats.get('LOW', 0)}**")
        lines.append("")

        lines.append("## 高优先级问题")
        lines.append("")
        high_risks = [r for r in self.risks if r.level == "HIGH"]
        if not high_risks:
            lines.append("- 暂无")
        else:
            for r in high_risks[:100]:
                lines.append(f"- [{r.code}] `{r.target}`：{r.message}")
        lines.append("")

        lines.append("## 模块清单")
        lines.append("")
        for _, mod in sorted(self.modules.items()):
            lines.append(f"### {mod.name}")
            lines.append(f"- 目录：`{mod.directory}`")
            lines.append(f"- manifest：`{mod.manifest_path or '无'}`")
            lines.append(f"- entry_class：`{mod.entry_class or '无'}`")
            lines.append(f"- entry：`{mod.entry or '无'}`")
            lines.append(f"- enabled：`{mod.enabled}`")
            lines.append(f"- Python 文件数：**{len(mod.py_files)}**")
            lines.append(f"- 类数：**{len(mod.classes)}**")
            lines.append(f"- Actions：`{', '.join(sorted(set(mod.action_names))) or '无'}`")
            lines.append(f"- Events：`{', '.join(sorted(set(mod.event_names))) or '无'}`")
            if mod.issues:
                lines.append("- Issues：")
                for issue in mod.issues:
                    lines.append(f"  - {issue}")
            else:
                lines.append("- Issues：无")
            lines.append("")

        lines.append("## 语法错误")
        lines.append("")
        if not self.syntax_errors:
            lines.append("- 暂无")
        else:
            for e in self.syntax_errors:
                lines.append(f"- `{e['file']}` line {e['line']}：{e['msg']}")
        lines.append("")

        lines.append("## 建议的二代封装前修复顺序")
        lines.append("")
        lines.append("1. 先清理 HIGH 风险：语法错误 / 缺 manifest / entry_class 找不到。")
        lines.append("2. 再清理模块标准问题：manifest、入口、动作声明一致性。")
        lines.append("3. 再处理循环依赖与跨层引用。")
        lines.append("4. 最后做统一启动入口、Trace、观测与封装。")
        lines.append("")

        (self.out_dir / "system_report.md").write_text("\n".join(lines), encoding="utf-8")


# ============================================================
# CLI
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="三花聚顶系统全量体检脚本（修复版）")
    parser.add_argument(
        "--root",
        type=str,
        default=".",
        help="项目根目录，默认当前目录",
    )
    parser.add_argument(
        "--exclude",
        type=str,
        nargs="*",
        default=[],
        help="额外排除目录名",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()

    if not root.exists() or not root.is_dir():
        print(f"[ERROR] 根目录不存在或不是目录：{root}")
        return 1

    exclude_dirs = set(DEFAULT_EXCLUDE_DIRS)
    exclude_dirs.update(args.exclude)

    auditor = SanhuaSystemAuditor(root=root, exclude_dirs=exclude_dirs)
    report = auditor.run()

    summary = report["summary"]
    print("=" * 72)
    print("三花聚顶系统体检完成")
    print("=" * 72)
    print(f"根目录           : {summary['root']}")
    print(f"Python 文件数    : {summary['python_files']}")
    print(f"模块数           : {summary['module_count']}")
    print(f"manifest 数      : {summary['manifest_count']}")
    print(f"类数             : {summary['class_count']}")
    print(f"函数数           : {summary['function_count']}")
    print(f"import 边数      : {summary['import_edge_count']}")
    print(f"action 边数      : {summary['action_edge_count']}")
    print(f"event 边数       : {summary['event_edge_count']}")
    print(f"语法错误数       : {summary['syntax_error_count']}")
    print(f"风险总数         : {summary['risk_count']}")
    print("")
    print(f"输出目录         : {auditor.out_dir}")
    print(f"Markdown 报告    : {auditor.out_dir / 'system_report.md'}")
    print(f"JSON 报告        : {auditor.out_dir / 'system_report.json'}")
    print(f"DOT 图           : {auditor.out_dir / 'module_graph.dot'}")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    sys.exit(main())
