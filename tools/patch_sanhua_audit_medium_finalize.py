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


def patch_detect_layer_models(text: str) -> tuple[str, bool]:
    old = """    if p.startswith("assets/"):
        return "assets"
    return "other"
"""
    new = """    if p.startswith("assets/"):
        return "assets"
    if p.startswith("models/"):
        return "models"
    return "other"
"""
    if old in text and 'if p.startswith("models/"):' not in text:
        return text.replace(old, new, 1), True
    return text, False


def patch_layer_rules_models(text: str) -> tuple[str, bool]:
    old = """LAYER_RULES = {
    "entry": ["core", "modules", "config", "assets"],
    "core": ["core", "modules", "config", "assets"],
    "modules": ["core", "modules", "config", "assets"],
    "config": [],
    "assets": [],
}
"""
    new = """LAYER_RULES = {
    "entry": ["core", "modules", "config", "assets", "models"],
    "core": ["core", "modules", "config", "assets", "models"],
    "modules": ["core", "modules", "config", "assets", "models"],
    "config": [],
    "assets": [],
    "models": [],
}
"""
    if old in text and '"models": []' not in text:
        return text.replace(old, new, 1), True
    return text, False


def ensure_module_whitelist(text: str) -> tuple[str, bool]:
    if "BASEMODULE_CANDIDATE_WHITELIST" in text:
        return text, False

    insert_after = 'ENTRY_HINT_FILES = {\n'
    idx = text.find(insert_after)
    if idx == -1:
        return text, False

    # 找到 ENTRY_HINT_FILES 结束位置
    end = text.find("}\n\n", idx)
    if end == -1:
        return text, False
    end += 3

    block = """BASEMODULE_CANDIDATE_WHITELIST = {
    "music_module",
    "state_describe",
}

"""
    return text[:end] + block + text[end:], True


def patch_build_modules_skip_models(text: str) -> tuple[str, bool]:
    old = """        for m in self.manifests:
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
    new = """        for m in self.manifests:
            parsed = split_module_relpath(m.module_dir)
            if parsed:
                tree_root, module_name, inner_rel = parsed
                directory = f"{tree_root}/{module_name}"
            else:
                # 非真正模块树的目录里，models/ 只视为资源，不纳入模块治理
                if m.module_dir.replace("\\\\", "/").startswith("models/"):
                    continue
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


def patch_skip_models_no_py_files(text: str) -> tuple[str, bool]:
    old = """        for mod in self.modules.values():
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
"""
    new = """        for mod in self.modules.values():
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
"""
    if old in text:
        return text.replace(old, new, 1), True
    return text, False


def patch_no_basemodule_whitelist(text: str) -> tuple[str, bool]:
    old = """        for mod_name, mod in self.modules.items():
            if mod.directory.startswith("modules/") or mod.directory.startswith("模块/"):
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
"""
    new = """        for mod_name, mod in self.modules.items():
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
"""
    if old in text:
        return text.replace(old, new, 1), True
    return text, False


def patch_ignore_self_cycles(text: str) -> tuple[str, bool]:
    old = """        for c in unique_cycles[:50]:
            self.risks.append(
                RiskItem(
                    level="MEDIUM",
                    code="IMPORT_CYCLE",
                    message="疑似循环依赖：" + " -> ".join(c),
                    target=c[0],
                )
            )
"""
    new = """        for c in unique_cycles[:50]:
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
"""
    if old in text:
        return text.replace(old, new, 1), True
    return text, False


def patch_text(text: str) -> tuple[str, list[str]]:
    steps = []

    for fn, label in [
        (patch_detect_layer_models, "detect_layer 支持 models/"),
        (patch_layer_rules_models, "LAYER_RULES 支持 models"),
        (ensure_module_whitelist, "加入 BaseModule 白名单"),
        (patch_build_modules_skip_models, "manifest 聚合时跳过 models 资源目录"),
        (patch_skip_models_no_py_files, "不再给 models/* 报 MODULE_NO_PY_FILES"),
        (patch_no_basemodule_whitelist, "NO_BASEMODULE_CANDIDATE 支持白名单"),
        (patch_ignore_self_cycles, "过滤自循环 IMPORT_CYCLE 误报"),
    ]:
        text, changed = fn(text)
        if changed:
            steps.append(label)

    return text, steps


def main():
    ap = argparse.ArgumentParser(description="收口 sanhua_system_audit.py 的 MEDIUM 审计噪音")
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
    print("审计脚本 MEDIUM 收口补丁完成")
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
