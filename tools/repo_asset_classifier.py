#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Classify repository assets into the V2-ASSET-001 layer policy.

This script is intentionally read-only for repository assets. It writes only
the generated reports under reports/repo_assets by default.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


CATEGORIES = {"mainline", "vendor", "runtime", "legacy", "unknown"}

EXPLICIT_MAINLINE_FILES = {
    "AGENTS.md": ("control_plane", "root control instructions"),
    "docs/AGENTS.md": ("control_plane", "docs control instructions"),
    "docs/COORDINATION_FLOW.md": ("control_plane", "coordination control document"),
    "docs/NEXT_ACTION.md": ("control_plane", "current control-plane action document"),
    "docs/TECH_DEBT.md": ("control_plane", "technical-debt governance document"),
    "docs/V1_DIRECTION.md": ("control_plane", "direction governance document"),
    "docs/REPO_ASSET_LAYERS.md": ("control_plane", "asset layer governance document"),
    "docs/ASSESSMENT_SCOPE_POLICY.md": ("control_plane", "assessment scope governance document"),
    "tests/test_baseline_e2e_governance.py": ("test", "current baseline governance test"),
    "tests/test_chat_routing_governance.py": ("test", "current chat routing governance test"),
    "tests/test_entry_dispatcher.py": ("test", "current entry dispatcher governance test"),
    "tools/repo_asset_classifier.py": ("asset_governance_tool", "current V2-ASSET-002 tool"),
}

EXPLICIT_MAINLINE_DIRS = {
    "core": ("runtime_code", "mainline core code"),
    "entry": ("entrypoint", "mainline entrypoints"),
    "modules": ("module_runtime", "mainline modules"),
}

EXPLICIT_BLACKLIST = {
    ".git": ("runtime", "vcs metadata"),
    ".pytest_cache": ("runtime", "test cache"),
    "__pycache__": ("runtime", "python cache"),
}

VENDOR_PREFIXES = {
    "llama.cpp",
    "juyuan_models",
    "piper-master",
    "third_party",
    "deps",
    "dependencies",
    "external",
    "models",
    "ollama_bin",
    "ollama_data",
    "ollama_models",
}

RUNTIME_PREFIXES = {
    ".venv",
    "venv",
    "logs",
    "runtime",
    "recordings",
    "rollback_snapshots",
    "audit_output",
    "reports",
    "cache",
    "tmp",
}

LEGACY_PREFIXES = {
    "_legacy_disabled",
    "legacy",
    "_audit_v2",
    "_audit_v2_2",
    "_audit_v2_clean",
    "_chatgpt_project_bundle_v2",
    "scaffold",
    "模块",
    "第二波",
}

GRAY_PREFIXES = {
    "tools",
    "docs",
    "config",
    "tests",
    "scripts",
    "data/memory",
}

MAINLINE_CONFIG_FILES = {
    "config/aliases.yaml",
    "config/aliases.darwin.yaml",
    "config/global.yaml",
    "config/global_config.yaml",
    "config/user.yaml",
    "config/release_v2_whitelist.txt",
}

RUNTIME_FILE_SUFFIXES = (
    ".log",
    ".jsonl",
    ".pkl",
    ".bak",
    ".zip",
    ".tar",
    ".rpm",
)

LEGACY_FILE_PREFIXES = (
    "fix_",
    "patch_",
    "repair_",
    "cleanup_",
    "rollback_",
)

PRUNE_DIRS = (
    VENDOR_PREFIXES
    | RUNTIME_PREFIXES
    | LEGACY_PREFIXES
    | {".git", ".pytest_cache", "__pycache__"}
)


@dataclass
class AssetRecord:
    path: str
    type: str
    category: str
    scope: str
    confidence: str
    reason: str
    matched_rule: str
    parent_category: str
    live_evidence: list[str]
    notes: str


def rel_path(path: Path, root: Path) -> str:
    rel = path.relative_to(root).as_posix()
    return "." if rel == "" else rel


def first_part(path: str) -> str:
    return path.split("/", 1)[0]


def starts_with(path: str, prefixes: Iterable[str]) -> str:
    for prefix in sorted(prefixes, key=len, reverse=True):
        if path == prefix or path.startswith(prefix + "/"):
            return prefix
    return ""


def parent_category(path: str, classified: dict[str, AssetRecord]) -> str:
    if "/" not in path:
        return ""
    parent = path.rsplit("/", 1)[0]
    while parent:
        rec = classified.get(parent)
        if rec:
            return rec.category
        if "/" not in parent:
            break
        parent = parent.rsplit("/", 1)[0]
    rec = classified.get(first_part(path))
    return rec.category if rec else ""


def classify(path: str, kind: str, classified: dict[str, AssetRecord]) -> AssetRecord:
    parent = parent_category(path, classified)
    live_evidence: list[str] = []
    notes = ""

    # 1. Explicit blacklist.
    black = starts_with(path, EXPLICIT_BLACKLIST)
    if black:
        category, reason = EXPLICIT_BLACKLIST[black]
        return AssetRecord(path, kind, category, "excluded", "high", reason, f"explicit_blacklist:{black}", parent, [], "")

    # 2. Explicit whitelist.
    if path in EXPLICIT_MAINLINE_FILES:
        scope, reason = EXPLICIT_MAINLINE_FILES[path]
        live_evidence.append(f"explicit_whitelist:{path}")
        return AssetRecord(path, kind, "mainline", scope, "high", reason, "explicit_whitelist", parent, live_evidence, "")

    if path in EXPLICIT_MAINLINE_DIRS:
        scope, reason = EXPLICIT_MAINLINE_DIRS[path]
        live_evidence.append(f"mainline_dir:{path}")
        return AssetRecord(path, kind, "mainline", scope, "high", reason, "explicit_whitelist_dir", parent, live_evidence, "")

    if path in MAINLINE_CONFIG_FILES:
        live_evidence.append(f"mainline_config:{path}")
        return AssetRecord(
            path,
            kind,
            "mainline",
            "config",
            "high",
            "configuration file approved for current startup/dispatch chain",
            "explicit_config_whitelist",
            parent,
            live_evidence,
            "",
        )

    # 3. Vendor / External path rules.
    vendor = starts_with(path, VENDOR_PREFIXES)
    if vendor:
        return AssetRecord(
            path,
            kind,
            "vendor",
            "external_dependency",
            "high",
            "vendor/external/model asset path",
            f"vendor_path:{vendor}",
            parent,
            [],
            "not scanned as Sanhua mainline code unless live evidence is provided",
        )

    # 4. Legacy / Runtime path rules.
    legacy = starts_with(path, LEGACY_PREFIXES)
    if legacy:
        return AssetRecord(
            path,
            kind,
            "legacy",
            "frozen_or_historical",
            "high",
            "legacy/frozen/audit asset path",
            f"legacy_path:{legacy}",
            parent,
            [],
            "not a mainline blocker unless explicitly referenced by live chain",
        )

    runtime = starts_with(path, RUNTIME_PREFIXES)
    if runtime:
        return AssetRecord(
            path,
            kind,
            "runtime",
            "runtime_artifact",
            "high",
            "runtime/cache/log/report artifact path",
            f"runtime_path:{runtime}",
            parent,
            [],
            "runtime evidence only; not a mainline blocker by default",
        )

    # 5. Filename pattern supplemental split.
    name = path.rsplit("/", 1)[-1]
    if name.startswith(LEGACY_FILE_PREFIXES):
        return AssetRecord(
            path,
            kind,
            "legacy",
            "historical_script",
            "medium",
            "historical fix/patch/repair filename pattern",
            "filename_pattern:legacy_script",
            parent,
            [],
            "pattern rule only; can be overridden by explicit work order",
        )

    if name.endswith(RUNTIME_FILE_SUFFIXES) or ".bak." in name:
        return AssetRecord(
            path,
            kind,
            "runtime",
            "runtime_or_archive_artifact",
            "medium",
            "log/archive/backup filename pattern",
            "filename_pattern:runtime_artifact",
            parent,
            [],
            "pattern rule only; can be overridden by live evidence",
        )

    # 6. Lightweight live mainline evidence.
    top = first_part(path)
    if top in {"core", "entry", "modules"}:
        live_evidence.append(f"under_mainline_dir:{top}")
        return AssetRecord(
            path,
            kind,
            "mainline",
            "runtime_code",
            "medium",
            "under approved mainline directory",
            f"lightweight_live_evidence:{top}",
            parent,
            live_evidence,
            "",
        )

    if top == "docs":
        return AssetRecord(
            path,
            kind,
            "unknown",
            "gray_docs",
            "low",
            "docs is gray; only explicit control/governance documents are mainline",
            "gray_zone:docs",
            parent,
            [],
            "requires manual review if used by current work order",
        )

    if top == "tests":
        return AssetRecord(
            path,
            kind,
            "unknown",
            "gray_tests",
            "low",
            "tests is gray; only current governance tests are mainline",
            "gray_zone:tests",
            parent,
            [],
            "requires manual review if used by current work order",
        )

    if starts_with(path, GRAY_PREFIXES):
        gray = starts_with(path, GRAY_PREFIXES)
        return AssetRecord(
            path,
            kind,
            "unknown",
            f"gray_{gray.replace('/', '_')}",
            "low",
            "gray directory requires per-file evidence",
            f"gray_zone:{gray}",
            parent,
            [],
            "unknown is expected; do not force classify for completeness",
        )

    # 7. Unknown.
    return AssetRecord(
        path,
        kind,
        "unknown",
        "needs_review",
        "low",
        "no rule matched",
        "default_unknown",
        parent,
        [],
        "unknown is not failure; requires evidence before classification",
    )


def iter_assets(root: Path) -> Iterable[tuple[Path, str]]:
    for path in sorted(root.iterdir(), key=lambda p: p.as_posix()):
        if path.name in {".", ".."}:
            continue
        kind = "dir" if path.is_dir() else "file"
        yield path, kind
        if not path.is_dir():
            continue
        if path.name in PRUNE_DIRS or path.name.startswith("ollama_"):
            continue
        for child in sorted(path.rglob("*"), key=lambda p: p.as_posix()):
            if any(part in PRUNE_DIRS for part in child.relative_to(root).parts[:-1]):
                continue
            yield child, "dir" if child.is_dir() else "file"


def build_records(root: Path) -> list[AssetRecord]:
    classified: dict[str, AssetRecord] = {}
    records: list[AssetRecord] = []
    for path, kind in iter_assets(root):
        rel = rel_path(path, root)
        rec = classify(rel, kind, classified)
        if rec.category not in CATEGORIES:
            raise ValueError(f"invalid category {rec.category!r} for {rel}")
        classified[rel] = rec
        records.append(rec)
    return records


def write_json(records: list[AssetRecord], out: Path, root: Path) -> None:
    payload = {
        "schema_version": 1,
        "root": str(root),
        "categories": sorted(CATEGORIES),
        "records": [asdict(rec) for rec in records],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_report(records: list[AssetRecord], out: Path) -> None:
    by_category = Counter(rec.category for rec in records)
    by_scope = Counter(rec.scope for rec in records)
    unknowns = [rec for rec in records if rec.category == "unknown"][:40]
    lines = [
        "# Repo Asset Report",
        "",
        "## Summary",
        "",
    ]
    for category in sorted(CATEGORIES):
        lines.append(f"- {category}: {by_category.get(category, 0)}")
    lines.extend(["", "## Scope Top Counts", ""])
    for scope, count in by_scope.most_common(20):
        lines.append(f"- {scope}: {count}")
    lines.extend([
        "",
        "## Policy Notes",
        "",
        "- unknown is not a failure; it means no sufficient mainline/vendor/runtime/legacy evidence was found.",
        "- vendor/runtime/legacy findings are not Sanhua mainline blockers unless live mainline evidence exists.",
        "- gray directories such as tools/docs/config/tests/scripts/data/memory require per-file review.",
        "- large vendor/runtime directories are recorded at the directory boundary and pruned by default.",
        "",
        "## Unknown Samples",
        "",
    ])
    if unknowns:
        for rec in unknowns:
            lines.append(f"- `{rec.path}` ({rec.type}, scope={rec.scope}, rule={rec.matched_rule})")
    else:
        lines.append("- none")
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify repository assets into governance categories.")
    parser.add_argument("root", nargs="?", default=".", help="repository root, default: .")
    parser.add_argument(
        "--out-dir",
        default="reports/repo_assets",
        help="output directory, default: reports/repo_assets",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    out_dir = (root / args.out_dir).resolve() if not Path(args.out_dir).is_absolute() else Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    records = build_records(root)
    json_path = out_dir / "repo_asset_map.json"
    report_path = out_dir / "repo_asset_report.md"
    write_json(records, json_path, root)
    write_report(records, report_path)

    print(f"wrote {json_path}")
    print(f"wrote {report_path}")
    print(f"records={len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
