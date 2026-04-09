#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "dependencies",
    "llama.cpp",
    "juyuan_models",
    "piper-master",
    "ollama_models",
    "rollback_snapshots",
    "build",
    "dist",
    "node_modules",
}


FILE_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".md", ".txt"}


@dataclass
class PythonSymbolIndex:
    top_level_functions: Set[str] = field(default_factory=set)
    classes: Set[str] = field(default_factory=set)
    class_methods: Dict[str, Set[str]] = field(default_factory=dict)

    def all_symbols(self) -> Set[str]:
        symbols = set(self.top_level_functions) | set(self.classes)
        for _, methods in self.class_methods.items():
            symbols |= methods
        return symbols


@dataclass
class AuditResult:
    existing_paths: List[str] = field(default_factory=list)
    missing_paths: List[str] = field(default_factory=list)

    existing_modules: List[str] = field(default_factory=list)
    missing_modules: List[str] = field(default_factory=list)

    existing_import_symbols: List[str] = field(default_factory=list)
    missing_import_symbols: List[str] = field(default_factory=list)

    probable_existing_identifiers: List[str] = field(default_factory=list)
    probable_missing_identifiers: List[str] = field(default_factory=list)


def is_excluded(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    parts = set(rel.parts)
    return any(part in EXCLUDE_DIRS for part in parts)


def iter_project_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if is_excluded(p, root):
            continue
        if p.suffix.lower() in FILE_SUFFIXES:
            files.append(p)
    return files


def module_name_from_path(root: Path, path: Path) -> str:
    rel = path.relative_to(root)
    parts = list(rel.parts)
    if parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def build_module_map(root: Path) -> Dict[str, Path]:
    module_map: Dict[str, Path] = {}
    for p in iter_project_files(root):
        if p.suffix.lower() != ".py":
            continue
        module_map[module_name_from_path(root, p)] = p
    return module_map


def build_relpath_set(root: Path) -> Set[str]:
    rels: Set[str] = set()
    for p in iter_project_files(root):
        rels.add(p.relative_to(root).as_posix())
    return rels


def extract_python_symbols(py_file: Path) -> PythonSymbolIndex:
    index = PythonSymbolIndex()
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception:
        return index

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            index.top_level_functions.add(node.name)
        elif isinstance(node, ast.ClassDef):
            index.classes.add(node.name)
            methods: Set[str] = set()
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.add(item.name)
            index.class_methods[node.name] = methods

    return index


def build_python_symbol_map(root: Path) -> Dict[str, PythonSymbolIndex]:
    symbol_map: Dict[str, PythonSymbolIndex] = {}
    for p in iter_project_files(root):
        if p.suffix.lower() == ".py":
            symbol_map[p.relative_to(root).as_posix()] = extract_python_symbols(p)
    return symbol_map


def load_text_from_clipboard() -> str:
    try:
        proc = subprocess.run(
            ["pbpaste"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        return proc.stdout
    except Exception as e:
        raise RuntimeError(f"读取剪贴板失败: {e}")


def load_input_text(args: argparse.Namespace) -> str:
    if args.text:
        return args.text

    if args.input:
        return Path(args.input).read_text(encoding="utf-8")

    if args.clipboard:
        return load_text_from_clipboard()

    if not sys.stdin.isatty():
        return sys.stdin.read()

    raise RuntimeError("没有输入内容。请使用 --text / --input / --clipboard，或通过管道传入内容。")


def extract_path_refs(text: str) -> List[str]:
    pattern = re.compile(
        r"(?:[A-Za-z0-9_\-]+/)+[A-Za-z0-9_\-]+\.(?:py|json|yaml|yml|md|txt)"
    )
    items = pattern.findall(text)
    return sorted(set(items))


def extract_imports(text: str) -> List[Tuple[str, Optional[str]]]:
    results: List[Tuple[str, Optional[str]]] = []

    from_pattern = re.compile(
        r"from\s+([A-Za-z_][A-Za-z0-9_\.]*)\s+import\s+([A-Za-z_][A-Za-z0-9_]*)"
    )
    import_pattern = re.compile(
        r"^\s*import\s+([A-Za-z_][A-Za-z0-9_\.]*)\s*$",
        re.MULTILINE,
    )

    for module, symbol in from_pattern.findall(text):
        results.append((module, symbol))

    for module in import_pattern.findall(text):
        results.append((module, None))

    return sorted(set(results))


def extract_backticked_identifiers(text: str) -> List[str]:
    items = re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", text)
    deny = {
        "python",
        "json",
        "yaml",
        "user",
        "assistant",
        "success",
        "failed",
        "core",
        "memory",
        "prompt",
        "chat",
    }
    filtered = []
    for x in items:
        if x.lower() in deny:
            continue
        filtered.append(x)
    return sorted(set(filtered))


def build_global_symbol_set(symbol_map: Dict[str, PythonSymbolIndex]) -> Set[str]:
    symbols: Set[str] = set()
    for idx in symbol_map.values():
        symbols |= idx.all_symbols()
    return symbols


def audit_answer(
    text: str,
    root: Path,
    relpaths: Set[str],
    module_map: Dict[str, Path],
    symbol_map: Dict[str, PythonSymbolIndex],
) -> AuditResult:
    result = AuditResult()

    # 1) 路径审计
    for ref in extract_path_refs(text):
        if ref in relpaths:
            result.existing_paths.append(ref)
        else:
            result.missing_paths.append(ref)

    # 2) import 审计
    for module, symbol in extract_imports(text):
        module_path = module_map.get(module)
        if module_path is None:
            result.missing_modules.append(module)
            if symbol:
                result.missing_import_symbols.append(f"{module}.{symbol}")
            continue

        result.existing_modules.append(module)

        if symbol:
            rel = module_path.relative_to(root).as_posix()
            idx = symbol_map.get(rel, PythonSymbolIndex())
            available = idx.top_level_functions | idx.classes
            if symbol in available:
                result.existing_import_symbols.append(f"{module}.{symbol}")
            else:
                result.missing_import_symbols.append(f"{module}.{symbol}")

    # 3) 反引号标识符审计（弱校验）
    global_symbols = build_global_symbol_set(symbol_map)
    for ident in extract_backticked_identifiers(text):
        if ident in global_symbols:
            result.probable_existing_identifiers.append(ident)
        else:
            result.probable_missing_identifiers.append(ident)

    # 去重排序
    for field_name in result.__dataclass_fields__:
        lst = getattr(result, field_name)
        setattr(result, field_name, sorted(set(lst)))

    return result


def print_section(title: str, items: List[str]) -> None:
    print("=" * 72)
    print(title)
    print("=" * 72)
    if not items:
        print("[]")
        return
    for x in items:
        print(f"- {x}")


def print_summary(result: AuditResult) -> None:
    print("=" * 72)
    print("审计摘要")
    print("=" * 72)
    print(f"existing_paths              = {len(result.existing_paths)}")
    print(f"missing_paths               = {len(result.missing_paths)}")
    print(f"existing_modules            = {len(result.existing_modules)}")
    print(f"missing_modules             = {len(result.missing_modules)}")
    print(f"existing_import_symbols     = {len(result.existing_import_symbols)}")
    print(f"missing_import_symbols      = {len(result.missing_import_symbols)}")
    print(f"probable_existing_identifiers = {len(result.probable_existing_identifiers)}")
    print(f"probable_missing_identifiers  = {len(result.probable_missing_identifiers)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="审计模型回答中提到的路径、导入、符号，判断是否贴合当前真实工程。"
    )
    parser.add_argument("--root", default=".", help="项目根目录，默认当前目录")
    parser.add_argument("--input", help="输入文本文件路径")
    parser.add_argument("--text", help="直接传入待审计文本")
    parser.add_argument("--clipboard", action="store_true", help="从 macOS 剪贴板读取内容")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        raise SystemExit(f"项目根目录不存在: {root}")

    text = load_input_text(args)
    if not text.strip():
        raise SystemExit("输入内容为空")

    relpaths = build_relpath_set(root)
    module_map = build_module_map(root)
    symbol_map = build_python_symbol_map(root)

    result = audit_answer(
        text=text,
        root=root,
        relpaths=relpaths,
        module_map=module_map,
        symbol_map=symbol_map,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "existing_paths": result.existing_paths,
                    "missing_paths": result.missing_paths,
                    "existing_modules": result.existing_modules,
                    "missing_modules": result.missing_modules,
                    "existing_import_symbols": result.existing_import_symbols,
                    "missing_import_symbols": result.missing_import_symbols,
                    "probable_existing_identifiers": result.probable_existing_identifiers,
                    "probable_missing_identifiers": result.probable_missing_identifiers,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    print_summary(result)
    print_section("存在的路径引用", result.existing_paths)
    print_section("缺失的路径引用", result.missing_paths)
    print_section("存在的模块导入", result.existing_modules)
    print_section("缺失的模块导入", result.missing_modules)
    print_section("存在的导入符号", result.existing_import_symbols)
    print_section("缺失的导入符号", result.missing_import_symbols)
    print_section("疑似存在的反引号标识符", result.probable_existing_identifiers)
    print_section("疑似缺失的反引号标识符", result.probable_missing_identifiers)


if __name__ == "__main__":
    main()
