#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import argparse
import logging
from rich.console import Console

console = Console()
log = logging.getLogger(__name__)

ENTRY_STUB = '''\
import logging

log = logging.getLogger(__name__)

def register_actions():
    """
    注册动作函数的地方
    """
    log.info(f"✨ [{__name__}] 默认入口被调用 (TODO: 实现业务逻辑)")
'''

MANIFEST_TEMPLATE = {
    "id": "",
    "name": "",
    "version": "1.0",
    "description": "",
    "author": "徐鹏鹏",
    "dependencies": []
}

def ensure_manifest(module_path, module_name):
    manifest_path = os.path.join(module_path, "manifest.json")
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 简单校验必须字段
            changed = False
            if "id" not in data or not data["id"]:
                data["id"] = module_name
                changed = True
            if "name" not in data or not data["name"]:
                data["name"] = module_name
                changed = True
            if changed:
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                console.log(f"[yellow]manifest.json 更新：{manifest_path}")
            return True
        except Exception as e:
            console.log(f"[red]解析 manifest.json 出错: {manifest_path}，错误：{e}")
            return False
    else:
        # 创建新的 manifest.json
        data = MANIFEST_TEMPLATE.copy()
        data["id"] = module_name
        data["name"] = module_name
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        console.log(f"[green]新建 manifest.json：{manifest_path}")
        return True

def ensure_module_py(module_path):
    module_py_path = os.path.join(module_path, "module.py")
    if os.path.exists(module_py_path):
        # 简单检查是否包含 register_actions 函数
        with open(module_py_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "def register_actions" not in content:
            with open(module_py_path, "w", encoding="utf-8") as f:
                f.write(ENTRY_STUB)
            console.log(f"[yellow]修复 module.py：{module_py_path}")
            return "fixed"
        else:
            return "exists"
    else:
        with open(module_py_path, "w", encoding="utf-8") as f:
            f.write(ENTRY_STUB)
        console.log(f"[green]新建 module.py：{module_py_path}")
        return "created"

def process_module(root_path, module_name):
    module_path = os.path.join(root_path, module_name)
    if not os.path.isdir(module_path):
        return None
    # 忽略非目录
    manifest_ok = ensure_manifest(module_path, module_name)
    module_status = ensure_module_py(module_path)
    return module_status

def main():
    parser = argparse.ArgumentParser(description="神秘入口自动工具 - 三花聚顶模块标准化")
    parser.add_argument("--root", type=str, default="modules", help="模块根目录，默认 modules")
    parser.add_argument("--fix-log", action="store_true", help="修复已有 module.py 的入口日志格式")
    args = parser.parse_args()

    root_path = args.root
    if not os.path.isdir(root_path):
        console.log(f"[red]目录不存在: {root_path}")
        return

    console.log(f"🛠️  开始标准化 {os.path.abspath(root_path)} ...")

    manifest_update_count = 0
    module_new_count = 0
    module_fixed_count = 0

    for entry in sorted(os.listdir(root_path)):
        path = os.path.join(root_path, entry)
        if not os.path.isdir(path):
            continue
        status = process_module(root_path, entry)
        if status == "created":
            module_new_count += 1
        elif status == "fixed":
            module_fixed_count += 1

    console.rule("[bold green]标准化结果[/]")
    console.print(f"• 新建 module.py 模块数: {module_new_count}")
    console.print(f"• 修复 module.py 模块数: {module_fixed_count}")
    console.print(f"• manifest.json 更新数: {manifest_update_count}（自动更新旧 manifest 内容的数量，暂未实现细节统计）")
    console.print("✅  完成。")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
