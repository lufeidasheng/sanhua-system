#!/usr/bin/env python3
"""
批量修复 TraceLogger 调用，把 error=、traceback= 等关键字挪到 extra={}
仅处理 core.core2_0/sanhuatongyu 目录下的 .py 文件
"""
import ast
import os
from pathlib import Path

PROJECT_ROOT = Path("/home/lufei/文档/聚核助手2.0/core.core2_0/sanhuatongyu")  # ← 按需调整
LOG_METHODS  = {"debug", "info", "warning", "error", "critical"}

class ExtraFixer(ast.NodeTransformer):
    """把 logger.xxx(..., foo=bar, extra={"x":1}) → logger.xxx(..., extra={"foo":bar,"x":1})"""

    def visit_Call(self, node: ast.Call):
        # 先递归子节点
        self.generic_visit(node)

        # 1. 确认是 logger.xxx(...) 调用
        if not isinstance(node.func, ast.Attribute):
            return node
        if node.func.attr not in LOG_METHODS:
            return node

        # 2. 分类关键字参数
        extra_kw = None
        other_kws = []
        for kw in node.keywords:
            if kw.arg == "extra":
                extra_kw = kw
            else:
                other_kws.append(kw)

        # 3-a 如果没有其他关键字 → 不改
        if not other_kws:
            return node

        # 3-b 构造新的 extra dict
        if extra_kw is None:
            # 没有 extra：把所有其他 kw → dict
            keys   = [ast.Constant(value=kw.arg) for kw in other_kws]
            values = [kw.value for kw in other_kws]
            extra_dict = ast.Dict(keys=keys, values=values)
        else:
            # 已有 extra：保留它，丢弃其他 kw
            extra_dict = extra_kw.value

        # 4. 组装新的关键字，仅包含 extra
        node.keywords = [ast.keyword(arg="extra", value=extra_dict)]
        return node

def fix_file(path: Path) -> bool:
    """返回 True 表示文件被修改"""
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False  # 跳过语法错误文件

    fixer = ExtraFixer()
    new_tree = fixer.visit(tree)
    ast.fix_missing_locations(new_tree)

    new_code = ast.unparse(new_tree)  # Python 3.9+

    if new_code != source:
        path.write_text(new_code, encoding="utf-8")
        print(f"Fixed  {path.relative_to(PROJECT_ROOT.parent)}")
        return True
    return False

def main():
    modified = 0
    for py in PROJECT_ROOT.rglob("*.py"):
        if fix_file(py):
            modified += 1
    print(f"\n✔ 完成，修改 {modified} 个文件")

if __name__ == "__main__":
    main()
