#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import ast
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


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
    "_audit",
    "_audit_v2",
    "_audit_v2_2",
    "_audit_v2_clean",
    "_chatgpt_project_bundle_v2",
    "_legacy_disabled",
    "audit_output",
    "fix_backups",
    "rollback_snapshots",
    "rollback_snapshots_runtime",
    "site-packages",
}

TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".yaml", ".yml"}
MAX_SCAN_BYTES = 512 * 1024
PLATFORM_HINTS = {
    "macos": ["afplay", "osascript", "open -a", "say ", "Apple Music", "Music.app"],
    "linux": ["amixer", "pactl", "aplay", "arecord", "xdg-open"],
    "windows": ["powershell", "winmm", "nircmd", "explorer.exe", "start "],
}


@dataclass
class Candidate:
    id: str
    dimension: str
    severity: str
    title: str
    summary: str
    file: str
    line: int
    evidence: str
    recommendation: str


def safe_read(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_SCAN_BYTES:
            return ""
    except Exception:
        return ""

    try:
        raw = path.read_bytes()
    except Exception:
        return ""

    if b"\x00" in raw:
        return ""

    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode(errors="ignore")


def iter_files(root: Path, suffixes: set[str] | None = None) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in EXCLUDED_DIRS and not d.startswith(".")
        )
        base = Path(dirpath)
        for name in sorted(filenames):
            path = base / name
            if suffixes and path.suffix.lower() not in suffixes:
                continue
            try:
                if path.stat().st_size > MAX_SCAN_BYTES:
                    continue
            except Exception:
                continue
            yield path


def rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def add_candidate(store: list[Candidate], *, dimension: str, severity: str, title: str,
                  summary: str, file: str, line: int, evidence: str, recommendation: str) -> None:
    cid = f"C{len(store) + 1:03d}"
    store.append(
        Candidate(
            id=cid,
            dimension=dimension,
            severity=severity,
            title=title,
            summary=summary,
            file=file,
            line=line,
            evidence=evidence[:240],
            recommendation=recommendation,
        )
    )


def scan_syntax_and_imports(root: Path, out: list[Candidate]) -> None:
    for path in iter_files(root, {".py"}):
        file_rel = rel(path, root)
        text = safe_read(path)
        try:
            tree = ast.parse(text, filename=file_rel)
        except SyntaxError as e:
            add_candidate(
                out,
                dimension="语法/导入问题",
                severity="high",
                title="Python 语法错误候选",
                summary="文件无法通过 AST 解析，存在直接阻塞导入风险。",
                file=file_rel,
                line=e.lineno or 1,
                evidence=f"{e.msg} (line={e.lineno}, offset={e.offset})",
                recommendation="优先单文件修复语法错误，避免启动期导入中断。",
            )
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod == "core.core2_0.sanhuatongyu.logger":
                    for alias in node.names:
                        if alias.name == "TraceLogger":
                            add_candidate(
                                out,
                                dimension="兼容/历史链问题",
                                severity="medium",
                                title="旧式 TraceLogger 导入链仍存在",
                                summary="项目仍保留历史兼容导入点，后续 logger 体系再变更时仍可能回归。",
                                file=file_rel,
                                line=node.lineno,
                                evidence=f"from {mod} import TraceLogger",
                                recommendation="保留兼容期间可接受；后续单开工单统一收敛到 get_logger。",
                            )
                if mod.endswith(".module") and file_rel.endswith("__init__.py"):
                    names = {alias.name for alias in node.names}
                    if {"entry", "register_actions"} & names:
                        add_candidate(
                            out,
                            dimension="模块协议问题",
                            severity="medium",
                            title="模块包导出对 module.py 结构有硬依赖",
                            summary="包级 __init__ 直接从 module.py 严格导入，易因字段缺失导致整包导入失败。",
                            file=file_rel,
                            line=node.lineno,
                            evidence=f"from {mod} import {', '.join(sorted(names))}",
                            recommendation="后续可收敛为安全导出层，避免单字段缺失拖垮整个模块包。",
                        )


def scan_module_protocol(root: Path, out: list[Candidate]) -> None:
    modules_root = root / "modules"
    if not modules_root.exists():
        return

    for mod_dir in sorted(p for p in modules_root.iterdir() if p.is_dir()):
        module_py = mod_dir / "module.py"
        init_py = mod_dir / "__init__.py"
        manifest_json = mod_dir / "manifest.json"

        if not module_py.exists():
            add_candidate(
                out,
                dimension="模块协议问题",
                severity="high",
                title="模块目录缺少 module.py",
                summary="模块目录存在但缺少核心实现文件，运行期加载协议可能不完整。",
                file=rel(mod_dir, root),
                line=1,
                evidence="missing module.py",
                recommendation="补齐 module.py 或从模块清单中移除该目录。",
            )
            continue

        text = safe_read(module_py)
        try:
            tree = ast.parse(text, filename=rel(module_py, root))
        except SyntaxError:
            continue

        top_level_funcs = {
            node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if "entry" not in top_level_funcs and "register_actions" not in top_level_funcs:
            add_candidate(
                out,
                dimension="模块协议问题",
                severity="medium",
                title="模块入口协议不完整候选",
                summary="module.py 未见 entry/register_actions，可能无法被现有加载链识别。",
                file=rel(module_py, root),
                line=1,
                evidence=f"top_level_funcs={sorted(top_level_funcs)[:8]}",
                recommendation="确认该模块是否属于标准加载协议；若是，补齐最小入口导出。",
            )

        if not init_py.exists():
            add_candidate(
                out,
                dimension="模块协议问题",
                severity="low",
                title="模块包缺少 __init__.py",
                summary="包级导出层缺失，历史导入链兼容性可能不稳定。",
                file=rel(mod_dir, root),
                line=1,
                evidence="missing __init__.py",
                recommendation="如该模块需要包路径导入，补齐最小 __init__.py 安全导出层。",
            )

        if not manifest_json.exists():
            add_candidate(
                out,
                dimension="模块协议问题",
                severity="low",
                title="模块目录缺少 manifest.json 候选",
                summary="若依赖 manifest 进行元数据扫描，模块可观测性会不足。",
                file=rel(mod_dir, root),
                line=1,
                evidence="missing manifest.json",
                recommendation="确认该项目当前是否统一依赖 manifest；若依赖，应补齐最小元数据。",
            )


def scan_runtime_candidates(root: Path, out: list[Candidate]) -> None:
    patterns = [
        (re.compile(r"except\s+Exception\s*:\s*pass"), "broad_except_pass", "广义异常被静默吞掉"),
        (re.compile(r"TODO|FIXME|待处理|未实现|stub", re.IGNORECASE), "todo_stub", "存在明显未完成功能标记"),
        (re.compile(r"fallback|degraded|demo|mock", re.IGNORECASE), "fallback_marker", "存在降级/演示型运行语义"),
    ]

    for path in iter_files(root, {".py", ".md", ".txt"}):
        file_rel = rel(path, root)
        text = safe_read(path)
        lines = text.splitlines()
        for idx, line in enumerate(lines, start=1):
            for pattern, key, desc in patterns:
                if pattern.search(line):
                    severity = "medium" if key == "broad_except_pass" else "low"
                    add_candidate(
                        out,
                        dimension="运行面候选问题",
                        severity=severity,
                        title=desc,
                        summary="静态扫描命中可能掩盖真实运行状态的问题点，建议后续按主线筛选。",
                        file=file_rel,
                        line=idx,
                        evidence=line.strip(),
                        recommendation="仅在命中主链时开最小工单，不顺手扩修。",
                    )
                    break


def scan_compatibility(root: Path, out: list[Candidate]) -> None:
    for path in iter_files(root):
        file_rel = rel(path, root)
        name = path.name
        if any(tag in name for tag in (".bak", ".txt")) and path.suffix in {".py", ".txt"}:
            add_candidate(
                out,
                dimension="兼容/历史链问题",
                severity="low",
                title="历史备份/镜像文件仍在代码树内",
                summary="历史文件与现行文件并存，容易干扰检索、审计和人工判断。",
                file=file_rel,
                line=1,
                evidence=name,
                recommendation="后续可单开清理工单，先确认是否仍承担回滚或取证作用。",
            )


def scan_control_plane(root: Path, out: list[Candidate]) -> None:
    docs = root / "docs"
    tech_debt = docs / "TECH_DEBT.md"
    next_action = docs / "NEXT_ACTION.md"
    for target, expected in (
        (tech_debt, "# 技术债台账"),
        (next_action, "# NEXT_ACTION"),
    ):
        if not target.exists():
            add_candidate(
                out,
                dimension="文档控制面检查",
                severity="high",
                title="控制面文档缺失",
                summary="当前控制面文档不存在，副施工位难以同步状态。",
                file=rel(target, root),
                line=1,
                evidence="missing file",
                recommendation="补齐文档骨架，并固定更新口径。",
            )
            continue
        text = safe_read(target)
        if expected not in text:
            add_candidate(
                out,
                dimension="文档控制面检查",
                severity="medium",
                title="控制面文档标题不符合约定",
                summary="文档存在但缺少预期标题，控制面约定可能已漂移。",
                file=rel(target, root),
                line=1,
                evidence=f"expected heading: {expected}",
                recommendation="维持固定标题，降低协作期歧义。",
            )


def scan_platform_dependencies(root: Path, out: list[Candidate]) -> None:
    for path in iter_files(root, {".py", ".sh"}):
        file_rel = rel(path, root)
        text = safe_read(path)
        lines = text.splitlines()
        for idx, line in enumerate(lines, start=1):
            for platform, hints in PLATFORM_HINTS.items():
                for hint in hints:
                    if hint in line:
                        add_candidate(
                            out,
                            dimension="平台后端硬依赖候选",
                            severity="medium",
                            title=f"{platform} 后端硬依赖痕迹",
                            summary="代码中存在平台命令/应用硬编码，后续可能需要能力探测与降级策略。",
                            file=file_rel,
                            line=idx,
                            evidence=line.strip(),
                            recommendation="若该链路进入主线，再单开工单补平台探测、reason 与降级语义。",
                        )
                        break
                else:
                    continue
                break


def dedupe(candidates: list[Candidate]) -> list[Candidate]:
    seen: set[tuple[str, str, int, str]] = set()
    out: list[Candidate] = []
    for item in candidates:
        key = (item.dimension, item.file, item.line, item.title)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def build_markdown(root: Path, candidates: list[Candidate], summary: dict) -> str:
    lines: list[str] = []
    lines.append("# 技术债候选扫描结果")
    lines.append("")
    lines.append("说明：")
    lines.append("- 本文件只记录候选，不直接回写正式技术债台账")
    lines.append("- 候选来自静态扫描，是否入正式台账需再按主线筛选")
    lines.append("")
    lines.append("## 扫描摘要")
    lines.append(f"- 项目根目录：`{root}`")
    lines.append(f"- 候选总数：`{summary['candidate_count']}`")
    lines.append(f"- Python 文件数：`{summary['python_files']}`")
    lines.append(f"- 模块目录数：`{summary['module_dirs']}`")
    lines.append("")
    lines.append("## 维度分布")
    for key, value in summary["dimension_counts"].items():
        lines.append(f"- {key}：`{value}`")
    lines.append("")
    lines.append("## 优先候选")
    for item in candidates[:15]:
        lines.append(f"### {item.id} - {item.title}")
        lines.append(f"- 维度：{item.dimension}")
        lines.append(f"- 严重度：{item.severity}")
        lines.append(f"- 文件：`{item.file}:{item.line}`")
        lines.append(f"- 摘要：{item.summary}")
        lines.append(f"- 证据：`{item.evidence}`")
        lines.append(f"- 建议：{item.recommendation}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="技术债候选静态扫描器")
    ap.add_argument("--root", default=".", help="项目根目录，默认当前目录")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    candidates: list[Candidate] = []

    scan_syntax_and_imports(root, candidates)
    scan_module_protocol(root, candidates)
    scan_runtime_candidates(root, candidates)
    scan_compatibility(root, candidates)
    scan_control_plane(root, candidates)
    scan_platform_dependencies(root, candidates)

    candidates = dedupe(candidates)
    severity_order = {"high": 0, "medium": 1, "low": 2}
    candidates.sort(key=lambda x: (severity_order.get(x.severity, 9), x.dimension, x.file, x.line))

    dimension_counts: dict[str, int] = {}
    for item in candidates:
        dimension_counts[item.dimension] = dimension_counts.get(item.dimension, 0) + 1

    summary = {
        "root": str(root),
        "candidate_count": len(candidates),
        "python_files": sum(1 for _ in iter_files(root, {".py"})),
        "module_dirs": len([p for p in (root / "modules").iterdir() if p.is_dir()]) if (root / "modules").exists() else 0,
        "dimension_counts": dimension_counts,
    }

    json_payload = {
        "summary": summary,
        "candidates": [asdict(item) for item in candidates],
    }

    out_dir = root / "audit_output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / "tech_debt_candidates.json"
    out_md = out_dir / "tech_debt_candidates.md"
    out_json.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md.write_text(build_markdown(root, candidates, summary), encoding="utf-8")

    print(f"candidate_count={len(candidates)}")
    print(f"json={out_json}")
    print(f"md={out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
