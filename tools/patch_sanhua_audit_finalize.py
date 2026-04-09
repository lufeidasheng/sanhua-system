#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


def safe_read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def safe_write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def backup_file(src: Path, backup_root: Path, root: Path) -> Path:
    rel = src.relative_to(root)
    dst = backup_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def ensure_legacy_exclude(text: str) -> tuple[str, bool]:
    if '"_legacy_disabled"' in text or "'_legacy_disabled'" in text:
        return text, False

    anchor = '    "site-packages",'
    if anchor in text:
        return text.replace(anchor, anchor + '\n    "_legacy_disabled",', 1), True

    return text, False


def ensure_split_module_relpath(text: str) -> tuple[str, bool]:
    if "def split_module_relpath(rel_path: str):" in text:
        return text, False

    helper = '''

def is_module_tree_path(rel_path: str) -> bool:
    rel_path = rel_path.replace("\\\\", "/")
    return rel_path.startswith("modules/") or rel_path.startswith("模块/")

def split_module_relpath(rel_path: str):
    """
    只接受真正的模块树路径：
    - modules/<mod_name>/...
    - 模块/<mod_name>/...
    返回: (tree_root, module_name, inner_rel)
    非法则返回 None
    """
    rel_path = rel_path.replace("\\\\", "/")
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
'''

    anchor = "def infer_module_name_from_dir(dir_path: Path) -> str:\n    return dir_path.name\n"
    if anchor in text:
        return text.replace(anchor, anchor + helper, 1), True

    return text, False


def patch_detect_layer(text: str) -> tuple[str, bool]:
    old = '    if p.startswith("modules/"):\n        return "modules"\n'
    new = '    if p.startswith("modules/") or p.startswith("模块/"):\n        return "modules"\n'
    if old in text and new not in text:
        return text.replace(old, new, 1), True
    return text, False


def patch_build_modules_pyfiles(text: str) -> tuple[str, bool]:
    old = """        for rel, fi in self.file_infos.items():
            if rel.startswith("modules/"):
                parts = rel.split("/")
                if len(parts) >= 2:
                    mod_name = parts[1]
                    if mod_name not in self.modules:
                        self.modules[mod_name] = ModuleInfo(
                            name=mod_name,
                            directory=f"modules/{mod_name}",
                        )
                    self.modules[mod_name].py_files.append(rel)
"""
    new = """        for rel, fi in self.file_infos.items():
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
"""
    if old in text:
        return text.replace(old, new, 1), True
    return text, False


def patch_build_modules_classes(text: str) -> tuple[str, bool]:
    old = """        for ci in self.class_infos:
            if ci.file.startswith("modules/"):
                parts = ci.file.split("/")
                if len(parts) >= 2:
                    mod_name = parts[1]
                    if mod_name not in self.modules:
                        self.modules[mod_name] = ModuleInfo(
                            name=mod_name,
                            directory=f"modules/{mod_name}",
                        )
                    self.modules[mod_name].classes.append(ci.qualname)
"""
    new = """        for ci in self.class_infos:
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
"""
    if old in text:
        return text.replace(old, new, 1), True
    return text, False


def patch_build_modules_actions_events(text: str) -> tuple[str, bool]:
    old = """        for ae in self.action_edges:
            if ae.source_file.startswith("modules/"):
                parts = ae.source_file.split("/")
                if len(parts) >= 2:
                    mod_name = parts[1]
                    if mod_name in self.modules and ae.action_name not in self.modules[mod_name].action_names:
                        self.modules[mod_name].action_names.append(ae.action_name)

        for ee in self.event_edges:
            if ee.source_file.startswith("modules/"):
                parts = ee.source_file.split("/")
                if len(parts) >= 2:
                    mod_name = parts[1]
                    if mod_name in self.modules and ee.event_name not in self.modules[mod_name].event_names:
                        self.modules[mod_name].event_names.append(ee.event_name)
"""
    new = """        for ae in self.action_edges:
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
"""
    if old in text:
        return text.replace(old, new, 1), True
    return text, False


def patch_module_risk_checks(text: str) -> tuple[str, bool]:
    changed = False

    old1 = 'if mod.directory.startswith("modules/") and not mod.manifest_path:'
    new1 = 'if (mod.directory.startswith("modules/") or mod.directory.startswith("模块/")) and not mod.manifest_path:'
    if old1 in text:
        text = text.replace(old1, new1)
        changed = True

    old2 = 'if mod.directory.startswith("modules/"):'
    new2 = 'if mod.directory.startswith("modules/") or mod.directory.startswith("模块/"):'
    if old2 in text:
        text = text.replace(old2, new2)
        changed = True

    return text, changed


def patch_manifest_binding(text: str) -> tuple[str, bool]:
    """
    让 manifest 聚合时，只把真正的模块树根目录作为模块；
    其他 core/entry 等仍保留原行为。
    """
    old = """        for m in self.manifests:
            module_name = m.module_name or infer_module_name_from_dir(self.root / m.module_dir)
            if module_name not in self.modules:
                self.modules[module_name] = ModuleInfo(
                    name=module_name,
                    directory=m.module_dir,
                )
            mod = self.modules[module_name]
"""
    new = """        for m in self.manifests:
            parsed = split_module_relpath(m.module_dir)
            if parsed:
                tree_root, module_name, inner_rel = parsed
                directory = f"{tree_root}/{module_name}"
            else:
                module_name = m.module_name or infer_module_name_from_dir(self.root / m.module_dir)
                directory = m.module_dir

            if module_name not in self.modules:
                self.modules[module_name] = ModuleInfo(
                    name=module_name,
                    directory=directory,
                )
            mod = self.modules[module_name]
"""
    if old in text:
        return text.replace(old, new, 1), True
    return text, False


def patch_text(text: str) -> tuple[str, list[str]]:
    steps = []

    for fn, label in [
        (ensure_legacy_exclude, "_legacy_disabled 排除目录"),
        (ensure_split_module_relpath, "split_module_relpath 模块路径识别"),
        (patch_detect_layer, "detect_layer 支持 模块/"),
        (patch_build_modules_pyfiles, "build_modules Python 文件归属"),
        (patch_build_modules_classes, "build_modules 类归属"),
        (patch_build_modules_actions_events, "build_modules action/event 归属"),
        (patch_module_risk_checks, "模块风险判断支持 模块/"),
        (patch_manifest_binding, "manifest 绑定模块根目录"),
    ]:
        text, changed = fn(text)
        if changed:
            steps.append(label)

    return text, steps


def main():
    ap = argparse.ArgumentParser(description="修补 sanhua_system_audit.py 的模块识别与归档排除规则")
    ap.add_argument("--root", required=True, help="项目根目录")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    target = root / "tools" / "sanhua_system_audit.py"

    if not target.exists():
        print(f"[ERROR] 找不到文件：{target}")
        raise SystemExit(1)

    original = safe_read(target)
    patched, steps = patch_text(original)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_file(target, backup_root, root)

    if patched == original:
        print("[SKIP] 未检测到需要修改的内容")
        print(f"[BACKUP] {backup}")
        return

    safe_write(target, patched)

    print("=" * 72)
    print("审计脚本补丁完成")
    print("=" * 72)
    print(f"[PATCHED] {target}")
    print(f"[BACKUP ] {backup}")
    print("")
    print("本次修改：")
    for s in steps:
        print(f" - {s}")
    print("")
    print("下一步建议：")
    print(f'  python3 "{target}" --root "{root}"')
    print("=" * 72)


if __name__ == "__main__":
    main()
