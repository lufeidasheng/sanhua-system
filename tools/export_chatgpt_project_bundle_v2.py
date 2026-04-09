#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
三花聚顶系统 / 大型本地仓库
导出适合上传到 ChatGPT Project 的“干净上下文包” v2

核心策略：
1. 默认排除：
   - 虚拟环境 / site-packages / bin / include / lib / share
   - _legacy_disabled
   - audit_output/fix_backups
   - audit_output/rollback_snapshots_runtime
   - __pycache__ / node_modules / build / dist / .git
   - 模型权重本体（.gguf/.bin/.safetensors/.pt/.pth/.onnx...）
   - 安装包 / 媒体 / 大部分日志 / .bak 文件

2. 默认保留：
   - core / entry / modules / config / utils / scripts / tools / tests / docs
   - 顶层关键文本文件（README.md / run_gui.sh / config.yaml 等）
   - 模块入口：模块/gui_entry, 模块/cli_entry, 模块/voice_entry
   - audit_output 下的摘要文件：
       action_edges.csv
       event_edges.csv
       imports_edges.csv
       module_graph.dot
       module_inventory.csv
       gui_boot_audit_report.json
       以及部分 *_report.json

3. 输出内容：
   - FILTERED_MIRROR/        过滤后的镜像目录（只含可上传文本与占位文件）
   - META/PROJECT_SUMMARY.json
   - META/SELECTED_FILES.txt
   - META/SKIPPED_FILES.txt
   - META/MODEL_PLACEHOLDERS.txt
   - META/DIRECTORY_TREE.txt
   - META/UPLOAD_RECOMMENDATION.md

推荐：
python3 tools/export_chatgpt_project_bundle_v2.py \
  --root "/Users/lufei/Desktop/聚核助手2.0" \
  --out  "/Users/lufei/Desktop/聚核助手2.0/_chatgpt_project_bundle_v2" \
  --force
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Tuple


TEXT_EXTS = {
    ".py", ".pyi",
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".java", ".kt", ".kts",
    ".go", ".rs", ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp",
    ".swift", ".mm", ".m",
    ".sh", ".bash", ".zsh", ".fish", ".command",
    ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".md", ".rst", ".txt",
    ".sql", ".csv", ".tsv",
    ".html", ".htm", ".xml",
    ".css", ".scss", ".sass", ".less", ".qss",
    ".env", ".example", ".sample",
    ".service", ".plist",
    ".dockerfile", ".gitignore", ".gitattributes",
    ".makefile", ".mk",
    ".jinja", ".j2",
    ".vue",
    ".proto",
    ".properties",
    ".bat", ".ps1",
    ".ipynb",
    ".dot",
}

TEXT_FILENAMES = {
    "dockerfile",
    "makefile",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "pipfile",
    "pipfile.lock",
    "readme",
    "license",
    "copying",
    "manifest.json",
    "aliases.yaml",
    "aliases.yml",
}

MODEL_EXTS = {
    ".gguf", ".bin", ".safetensors", ".pt", ".pth", ".ckpt",
    ".onnx", ".engine", ".tflite", ".pb", ".mlmodel", ".keras"
}

INSTALLER_AND_BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".icns",
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a",
    ".mp4", ".mov", ".mkv", ".avi", ".webm",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar", ".dmg", ".pkg", ".rpm",
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
    ".db", ".sqlite", ".sqlite3",
    ".so", ".dylib", ".dll", ".a", ".o", ".class",
    ".whl", ".egg", ".pyc",
}

COMMON_NOISE_DIRS = {
    ".git", ".hg", ".svn",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    ".idea", ".vscode", ".vs",
    "node_modules", "dist", "build", "out", "target",
    ".next", ".nuxt", ".parcel-cache",
    ".cache", "cache", "tmp", "temp",
    ".dart_tool", ".gradle",
    ".DS_Store",
}

VENV_DIR_NAMES = {
    ".venv", "venv", "env", ".env", "virtualenv", ".virtualenv"
}

ACTIVE_TOP_LEVEL_DIRS = {
    "core",
    "entry",
    "modules",
    "config",
    "utils",
    "scripts",
    "tools",
    "tests",
    "docs",
    "audit_output",
    "models",
    "模块",
    "assets",
}

AUDIT_SUMMARY_FILES = {
    "action_edges.csv",
    "event_edges.csv",
    "imports_edges.csv",
    "module_graph.dot",
    "module_inventory.csv",
    "gui_boot_audit_report.json",
    "gui_main.stable_20260330.py",
}

AUDIT_SUMMARY_PATTERNS = [
    re.compile(r".*_report\.json$", re.IGNORECASE),
]

ROOT_ALLOWLIST_FILES = {
    "README.md",
    "README.MD",
    "__init__.py",
    "run_gui.sh",
    "config.py",
    "config.yaml",
    "default_config.yaml",
    "module_loader.py",
    "module_standardizer.py",
    "main_controller.py",
    "health_checker.py",
    "health_report.md",
    "code_metrics.csv",
    "models.txt",
    "structure.txt",
    "standardize_report.md",
}

ROOT_DENY_PATTERNS = [
    re.compile(r".*\.log$", re.IGNORECASE),
    re.compile(r".*\.bak(\..*)?$", re.IGNORECASE),
    re.compile(r"Miniconda.*", re.IGNORECASE),
    re.compile(r".*\.(rpm|dmg|pkg|tar|gz|zip|7z|rar)$", re.IGNORECASE),
]

CHINESE_MODULE_ENTRY_ALLOWLIST = {
    "gui_entry",
    "cli_entry",
    "voice_entry",
}

DEFAULT_MAX_TEXT_KB = 1024
DEFAULT_LOG_TAIL_LINES = 300


@dataclass
class Record:
    relpath: str
    action: str
    reason: str
    size: int = 0


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, data: dict) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def is_text_file(path: Path) -> bool:
    ext = path.suffix.lower()
    name = path.name.lower()

    if ext in TEXT_EXTS or name in TEXT_FILENAMES:
        return True

    try:
        data = path.read_bytes()[:4096]
    except Exception:
        return False

    if b"\x00" in data:
        return False
    if not data:
        return True

    printable = sum(1 for b in data if 9 <= b <= 13 or 32 <= b <= 126 or b >= 128)
    return printable / max(len(data), 1) > 0.85


def read_text(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return path.read_text(encoding=enc, errors="replace")
        except Exception:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def tail_lines(text: str, n: int) -> str:
    arr = text.splitlines()
    return "\n".join(arr[-n:])


def trim_text(text: str, max_kb: int) -> Tuple[str, bool]:
    limit = max_kb * 1024
    data = text.encode("utf-8", errors="replace")
    if len(data) <= limit:
        return text, False

    half = limit // 2
    head = data[:half].decode("utf-8", errors="replace")
    tail = data[-half:].decode("utf-8", errors="replace")
    merged = head + "\n\n# ====== [中间内容已截断] ======\n\n" + tail
    return merged, True


def path_has_venv_signature(root: Path) -> bool:
    return (root / "pyvenv.cfg").exists()


def should_exclude_root_child(name: str, root: Path, active_only: bool) -> Tuple[bool, str]:
    if name in COMMON_NOISE_DIRS:
        return True, f"common_noise_dir:{name}"

    if active_only and name not in ACTIVE_TOP_LEVEL_DIRS and not (root / name).is_file():
        return True, f"not_in_active_top_level_dirs:{name}"

    if name in VENV_DIR_NAMES:
        return True, f"venv_dir:{name}"

    if path_has_venv_signature(root) and name in {"bin", "include", "lib", "share"}:
        return True, f"venv_structure:{name}"

    if name == "_legacy_disabled":
        return True, "legacy_disabled"

    return False, ""


def matches_any(name: str, patterns: Iterable[re.Pattern]) -> bool:
    return any(p.match(name) for p in patterns)


def is_model_file(path: Path, rel: str) -> bool:
    if path.suffix.lower() in MODEL_EXTS:
        return True
    rel_lower = rel.lower()
    if rel_lower.startswith("models/"):
        return True
    return False


def should_keep_audit_file(rel: str, name: str, keep_audit_summary: bool) -> Tuple[bool, str]:
    if not keep_audit_summary:
        return False, "audit_summary_disabled"

    if name in AUDIT_SUMMARY_FILES:
        return True, "audit_summary_allowlist"

    if matches_any(name, AUDIT_SUMMARY_PATTERNS):
        return True, "audit_summary_pattern"

    return False, "audit_non_summary"


def should_keep_root_file(path: Path) -> Tuple[bool, str]:
    name = path.name

    if name in ROOT_ALLOWLIST_FILES:
        return True, "root_allowlist"

    if matches_any(name, ROOT_DENY_PATTERNS):
        return False, "root_deny_pattern"

    if path.suffix.lower() in INSTALLER_AND_BINARY_EXTS:
        return False, "root_binary_or_installer"

    if is_text_file(path):
        return True, "root_text_file"

    return False, "root_non_text"


def should_keep_chinese_module_subdir(name: str) -> Tuple[bool, str]:
    if name in CHINESE_MODULE_ENTRY_ALLOWLIST:
        return True, "official_entry_module"
    return False, "non_entry_module_under_模块"


def classify(rel: str, root: Path, path: Path, active_only: bool, keep_audit_summary: bool) -> Tuple[str, str]:
    parts = rel.split("/")
    top = parts[0]
    name = path.name

    if path.is_dir():
        if top == "audit_output":
            if len(parts) >= 2 and parts[1] in {"fix_backups", "rollback_snapshots_runtime"}:
                return "skip", f"audit_history_dir:{parts[1]}"
            return "descend", "audit_output"

        if top == "模块":
            if len(parts) == 1:
                return "descend", "模块_root"
            if len(parts) == 2:
                keep, reason = should_keep_chinese_module_subdir(parts[1])
                return ("descend" if keep else "skip", reason)
            return "descend", "模块_kept_subtree"

        return "descend", "normal_dir"

    # 文件
    if name.startswith(".DS_Store"):
        return "skip", "mac_metadata"

    if ".bak" in name:
        return "skip", "backup_file"

    if is_model_file(path, rel):
        return "placeholder", "model_placeholder"

    if top == "audit_output":
        keep, reason = should_keep_audit_file(rel, name, keep_audit_summary)
        return ("copy" if keep else "skip", reason)

    if top == "assets":
        if is_text_file(path):
            return "copy", "text_asset"
        return "skip", "binary_asset"

    if len(parts) == 1:
        keep, reason = should_keep_root_file(path)
        return ("copy" if keep else "skip", reason)

    if path.suffix.lower() in INSTALLER_AND_BINARY_EXTS:
        return "skip", "binary_or_media"

    if path.suffix.lower() == ".log":
        return "excerpt", "log_tail_excerpt"

    if is_text_file(path):
        return "copy", "text_file"

    return "skip", "non_text"


def build_tree(paths: List[str]) -> str:
    tree = {}

    for rel in sorted(paths):
        node = tree
        for part in rel.split("/"):
            node = node.setdefault(part, {})

    lines: List[str] = []

    def walk(node: dict, prefix: str = "") -> None:
        items = sorted(node.items(), key=lambda x: (len(x[1]) == 0, x[0].lower()))
        for idx, (name, child) in enumerate(items):
            last = idx == len(items) - 1
            connector = "└── " if last else "├── "
            lines.append(prefix + connector + name)
            if child:
                walk(child, prefix + ("    " if last else "│   "))

    walk(tree)
    return "\n".join(lines)


def remove_out(out: Path, force: bool) -> None:
    if out.exists():
        if not force:
            raise SystemExit(f"输出目录已存在：{out}\n请删除后重试，或加 --force")
        shutil.rmtree(out)
    ensure_dir(out)


def export_bundle(
    root: Path,
    out: Path,
    active_only: bool,
    keep_audit_summary: bool,
    max_text_kb: int,
    log_tail_lines: int,
) -> None:
    mirror = out / "FILTERED_MIRROR"
    meta = out / "META"
    ensure_dir(mirror)
    ensure_dir(meta)

    selected: List[Record] = []
    skipped: List[Record] = []
    placeholders: List[Record] = []

    for current_root, dirs, files in os.walk(root, topdown=True):
        current = Path(current_root)

        # 动态目录过滤
        kept_dirs = []
        for d in dirs:
            dp = current / d
            rel = safe_rel(dp, root)

            if current == root:
                excluded, reason = should_exclude_root_child(d, root, active_only)
                if excluded:
                    skipped.append(Record(rel, "skip_dir", reason, 0))
                    continue

            if d in COMMON_NOISE_DIRS:
                skipped.append(Record(rel, "skip_dir", f"common_noise_dir:{d}", 0))
                continue

            if d in VENV_DIR_NAMES:
                skipped.append(Record(rel, "skip_dir", f"venv_dir:{d}", 0))
                continue

            # 细粒度目录分类
            decision, reason = classify(rel, root, dp, active_only, keep_audit_summary)
            if decision == "skip":
                skipped.append(Record(rel, "skip_dir", reason, 0))
                continue

            kept_dirs.append(d)

        dirs[:] = kept_dirs

        for f in files:
            fp = current / f
            try:
                st = fp.stat()
            except Exception as exc:
                skipped.append(Record(safe_rel(fp, root), "skip_file", f"stat_error:{exc}", 0))
                continue

            if not stat.S_ISREG(st.st_mode):
                continue

            rel = safe_rel(fp, root)
            decision, reason = classify(rel, root, fp, active_only, keep_audit_summary)

            if decision == "skip":
                skipped.append(Record(rel, "skip_file", reason, st.st_size))
                continue

            if decision == "placeholder":
                placeholder_path = mirror / f"{rel}.placeholder.txt"
                content = (
                    f"model_placeholder=true\n"
                    f"original_relpath={rel}\n"
                    f"original_name={fp.name}\n"
                    f"size_bytes={st.st_size}\n"
                    f"reason=真实模型权重/模型目录已排除，仅保留占位\n"
                )
                write_text(placeholder_path, content)
                placeholders.append(Record(rel, "placeholder", reason, st.st_size))
                continue

            if decision == "excerpt":
                text = read_text(fp)
                excerpt = tail_lines(text, log_tail_lines)
                excerpt_path = mirror / f"{rel}.excerpt.txt"
                write_text(excerpt_path, excerpt)
                selected.append(Record(rel, "excerpt", reason, st.st_size))
                continue

            if decision == "copy":
                text = read_text(fp)
                text, trimmed = trim_text(text, max_text_kb)
                dst = mirror / rel
                write_text(dst, text)
                selected.append(Record(rel, "copy_trimmed" if trimmed else "copy", reason, st.st_size))
                continue

            skipped.append(Record(rel, "skip_file", f"unknown_decision:{decision}", st.st_size))

    selected_rel = [r.relpath for r in selected]
    placeholder_rel = [r.relpath for r in placeholders]
    tree_text = build_tree(selected_rel + [f"{p}.placeholder.txt" for p in placeholder_rel])

    write_text(meta / "DIRECTORY_TREE.txt", tree_text + ("\n" if tree_text else ""))
    write_text(
        meta / "SELECTED_FILES.txt",
        "\n".join(f"{r.relpath}\t{r.action}\t{r.reason}\t{r.size}" for r in selected) + ("\n" if selected else "")
    )
    write_text(
        meta / "SKIPPED_FILES.txt",
        "\n".join(f"{r.relpath}\t{r.action}\t{r.reason}\t{r.size}" for r in skipped) + ("\n" if skipped else "")
    )
    write_text(
        meta / "MODEL_PLACEHOLDERS.txt",
        "\n".join(f"{r.relpath}\t{r.action}\t{r.reason}\t{r.size}" for r in placeholders) + ("\n" if placeholders else "")
    )

    summary = {
        "root": str(root),
        "out": str(out),
        "active_only": active_only,
        "keep_audit_summary": keep_audit_summary,
        "max_text_kb": max_text_kb,
        "log_tail_lines": log_tail_lines,
        "selected_count": len(selected),
        "placeholder_count": len(placeholders),
        "skipped_count": len(skipped),
        "selected_total_bytes": sum(r.size for r in selected),
        "placeholder_original_total_bytes": sum(r.size for r in placeholders),
        "top_level_strategy": {
            "keep": sorted(ACTIVE_TOP_LEVEL_DIRS),
            "exclude_always": [
                "_legacy_disabled",
                "venv/.venv/env",
                "bin/include/lib/share (when pyvenv.cfg exists)",
                "audit_output/fix_backups",
                "audit_output/rollback_snapshots_runtime",
                "__pycache__",
                "node_modules",
                "build/dist/target",
                "model weights",
                "*.bak*",
            ],
            "audit_summary_files": sorted(AUDIT_SUMMARY_FILES),
            "chinese_entry_modules": sorted(CHINESE_MODULE_ENTRY_ALLOWLIST),
        },
    }
    write_json(meta / "PROJECT_SUMMARY.json", summary)

    upload_md = f"""# 上传建议

## 第一批先传
1. META/PROJECT_SUMMARY.json
2. META/DIRECTORY_TREE.txt
3. META/SELECTED_FILES.txt
4. META/MODEL_PLACEHOLDERS.txt
5. FILTERED_MIRROR/README.md（如果存在）
6. FILTERED_MIRROR/core/ 关键文件
7. FILTERED_MIRROR/entry/ 关键入口
8. FILTERED_MIRROR/modules/ 关键模块
9. FILTERED_MIRROR/config/aliases.yaml（如果存在）
10. FILTERED_MIRROR/audit_output/module_inventory.csv
11. FILTERED_MIRROR/audit_output/imports_edges.csv
12. FILTERED_MIRROR/audit_output/action_edges.csv
13. FILTERED_MIRROR/audit_output/event_edges.csv

## 第二批按需传
- FILTERED_MIRROR/tools/
- FILTERED_MIRROR/tests/
- FILTERED_MIRROR/模块/gui_entry
- FILTERED_MIRROR/模块/cli_entry
- FILTERED_MIRROR/模块/voice_entry

## 不要传
- 原始 models/*.gguf 等权重
- _legacy_disabled
- audit_output/fix_backups
- audit_output/rollback_snapshots_runtime
- 原始 venv / site-packages
"""
    write_text(meta / "UPLOAD_RECOMMENDATION.md", upload_md)

    print("✅ 导出完成")
    print(f"项目根目录: {root}")
    print(f"输出目录:   {out}")
    print(f"已保留文件: {len(selected)}")
    print(f"模型占位:   {len(placeholders)}")
    print(f"已跳过:     {len(skipped)}")
    print(f"目录树:     {meta / 'DIRECTORY_TREE.txt'}")
    print(f"摘要:       {meta / 'PROJECT_SUMMARY.json'}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导出适合 ChatGPT Project 的干净上下文包 v2")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--out", required=True, help="输出目录")
    parser.add_argument("--force", action="store_true", help="输出目录已存在时强制覆盖")
    parser.add_argument("--no-active-only", action="store_true", help="关闭主干目录白名单模式")
    parser.add_argument("--no-audit-summary", action="store_true", help="不保留 audit_output 摘要文件")
    parser.add_argument("--max-text-kb", type=int, default=DEFAULT_MAX_TEXT_KB, help="单个文本文件最大保留 KB，超过则头尾截断")
    parser.add_argument("--log-tail-lines", type=int, default=DEFAULT_LOG_TAIL_LINES, help="日志只保留尾部多少行")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.root).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()

    if not root.exists() or not root.is_dir():
        raise SystemExit(f"项目根目录不存在或不是目录：{root}")

    remove_out(out, args.force)

    export_bundle(
        root=root,
        out=out,
        active_only=not args.no_active_only,
        keep_audit_summary=not args.no_audit_summary,
        max_text_kb=args.max_text_kb,
        log_tail_lines=args.log_tail_lines,
    )


if __name__ == "__main__":
    main()
