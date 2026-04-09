#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


KEYWORDS = {
    "chat", "ask", "reply", "send", "submit", "message", "input", "prompt",
    "assistant", "user", "runtime", "aicore", "chatonly", "history", "bubble",
    "append", "response", "route", "dispatch"
}


class MethodProbe(ast.NodeVisitor):
    def __init__(self):
        self.calls = []
        self.attrs = set()
        self.names = set()
        self.constants = []

    def visit_Call(self, node: ast.Call):
        target = self._expr_name(node.func)
        if target:
            self.calls.append(target)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        name = self._expr_name(node)
        if name:
            self.attrs.add(name)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        self.names.add(node.id)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, str):
            self.constants.append(node.value)
        self.generic_visit(node)

    def _expr_name(self, node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = self._expr_name(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        return None


def score_method(class_name: str, method_name: str, probe: MethodProbe):
    score = 0
    reasons = []

    method_l = method_name.lower()
    class_l = class_name.lower()

    for k in KEYWORDS:
        if k in method_l:
            score += 4
            reasons.append(f"method_name:{k}")

    for k in KEYWORDS:
        if k in class_l:
            score += 3
            reasons.append(f"class_name:{k}")

    joined_calls = " | ".join(probe.calls).lower()
    joined_attrs = " | ".join(sorted(probe.attrs)).lower()
    joined_consts = " | ".join(probe.constants).lower()

    for k in KEYWORDS:
        if k in joined_calls:
            score += 2
            reasons.append(f"call:{k}")
        if k in joined_attrs:
            score += 1
            reasons.append(f"attr:{k}")
        if k in joined_consts:
            score += 2
            reasons.append(f"const:{k}")

    hot = [
        "self.ac", "self.runtime", "chatonly", "aicore", "send", "reply",
        "append", "message", "input", "assistant", "user"
    ]
    blob = f"{joined_calls} || {joined_attrs} || {joined_consts}"
    for h in hot:
        if h in blob:
            score += 2
            reasons.append(f"hot:{h}")

    return score, reasons


def main() -> int:
    parser = argparse.ArgumentParser(description="静态扫描 gui_main.py 的聊天入口")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--top", type=int, default=20, help="输出前 N 个候选")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    target = root / "entry" / "gui_entry" / "gui_main.py"

    print("=" * 96)
    print("SCAN GUI CHAT ROUTE V1")
    print("=" * 96)
    print(f"root   : {root}")
    print(f"target : {target}")

    if not target.exists():
        print("[ERROR] target_not_found")
        return 2

    source = target.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(target))

    results = []

    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue

        class_name = node.name

        for sub in node.body:
            if not isinstance(sub, ast.FunctionDef):
                continue

            method_name = sub.name
            probe = MethodProbe()
            probe.visit(sub)

            score, reasons = score_method(class_name, method_name, probe)
            if score <= 0:
                continue

            results.append({
                "class": class_name,
                "method": method_name,
                "lineno": sub.lineno,
                "score": score,
                "reasons": reasons[:20],
                "top_calls": probe.calls[:20],
                "top_attrs": sorted(probe.attrs)[:25],
                "string_hits": [
                    x for x in probe.constants
                    if any(k in x.lower() for k in KEYWORDS)
                ][:15],
            })

    results.sort(key=lambda x: (-x["score"], x["lineno"], x["class"], x["method"]))

    print("\n[candidates]")
    for item in results[:args.top]:
        print("-" * 96)
        print(f"{item['class']}.{item['method']}  (line={item['lineno']}, score={item['score']})")
        print(f"reasons    : {item['reasons']}")
        print(f"top_calls  : {item['top_calls']}")
        print(f"top_attrs  : {item['top_attrs']}")
        print(f"string_hits: {item['string_hits']}")

    report = root / "audit_output" / "scan_gui_chat_route_v1_report.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 96)
    print(f"report_json : {report}")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
