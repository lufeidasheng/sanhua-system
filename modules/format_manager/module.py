#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三花聚顶 · format_manager（企业版 v1.0.2）
功能：统一格式化输出（代码/文本/表格/错误/文件），带安全清洗、截断与事件总线兼容。
作者：三花聚顶开发团队
"""

from __future__ import annotations
import os
import re
import ast
import html
import json
import textwrap
import hashlib
from typing import Optional, Dict, Any, List

# === 三花聚顶基座 ===
from core.core2_0.sanhuatongyu.module.base import BaseModule
from core.core2_0.sanhuatongyu.logger import get_logger
from core.core2_0.sanhuatongyu.action_dispatcher import dispatcher as ACTION_MANAGER

log = get_logger("format_manager")

# --------------------------
# 常量/配置
# --------------------------
SUPPORTED_LANGUAGES = [
    "python", "javascript", "java", "c", "cpp", "go", "rust", "ruby", "php",
    "swift", "kotlin", "scala", "html", "css", "sql", "bash", "yaml", "json",
    "typescript", "markdown", "xml", "perl", "lua", "dockerfile", "text"
]
MAX_OUTPUT_SIZE = 10 * 1024 * 1024       # 10MB
MAX_CODE_BLOCK_LINES = 1000              # 代码块最大行数

# --------------------------
# 核心实现
# --------------------------
class FormatManagerCore:
    def __init__(self):
        self.security_checks_enabled = True
        self.log_output = False
        log.info("格式化管理器核心初始化完成")

    # ---- 配置开关 ----
    def enable_security_checks(self, enable: bool):
        self.security_checks_enabled = enable
        log.info(f"安全检查已{'启用' if enable else '禁用'}")

    def set_log_output(self, enable: bool):
        self.log_output = enable
        log.info(f"输出日志已{'启用' if enable else '禁用'}")

    # ---- 语言检测 ----
    def _detect_language(self, code: str) -> str:
        patterns = {
            "python": r"^\s*(import |from |def |class |print\()",
            "javascript": r"^\s*(function |const |let |var |console\.log\()",
            "java": r"^\s*(import java\.|public class |System\.out\.print)",
            "c": r"^\s*#include\s+<|printf\(",
            "cpp": r"^\s*#include\s+<|std::cout\s?<<",
            "html": r"<html>|<!DOCTYPE html>|<head>|<body>",
            "sql": r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER)\s",
            "bash": r"^\s*#!\/bin\/bash|^\s*echo\s",
        }
        for lang, pat in patterns.items():
            if re.search(pat, code, re.IGNORECASE | re.MULTILINE):
                return lang
        try:  # AST 作为 python 兜底
            ast.parse(code)
            return "python"
        except Exception:
            pass
        return "text"

    # ---- 安全清洗 ----
    def _sanitize(self, content: str) -> str:
        if len(content) > MAX_OUTPUT_SIZE:
            log.warning(f"输出内容过大({len(content)} bytes)，已被截断提示")
            return "[输出内容过大，已被截断]"
        sanitized = html.escape(content)
        for pat in [r"<script[^>]*>.*?</script>", r"javascript:", r"on\w+\s*=", r"<\?php"]:
            sanitized = re.sub(pat, "[removed]", sanitized, flags=re.IGNORECASE | re.DOTALL)
        return sanitized

    # ---- 代码块截断 ----
    def _truncate_code(self, code: str, max_lines: int = MAX_CODE_BLOCK_LINES) -> str:
        lines = code.splitlines()
        if len(lines) > max_lines:
            head = lines[: max_lines // 2]
            tail = lines[-max_lines // 2 :]
            omitted = len(lines) - max_lines
            log.warning(f"代码块过大({len(lines)} 行)，中间省略 {omitted} 行")
            return "\n".join(head + [f"\n# ... 省略 {omitted} 行 ...\n"] + tail)
        return code

    # ---- 智能代码判定 ----
    def is_code(self, text: str) -> bool:
        if not text or not text.strip():
            return False
        code_patterns = [
            r"\b(def|class|import|from)\b",
            r"\b(function|var|let|const|console\.log)\b",
            r"\b(public|private|class|import)\b",
            r"\b(#include|printf)\b",
            r"\b(func|package)\b",
            r"\b(fn|mod|use)\b",
            r"^\s*<\?php",
            r"^\s*#!",
            r"\b(begin|end)\b",
            r"^\s*//|^\s*/\*|^\s*\*",
            r"^\s*\{|\}",
        ]
        if any(re.search(p, text, re.MULTILINE) for p in code_patterns):
            return True
        try:
            ast.parse(text)
            return True
        except Exception:
            pass
        density = sum(1 for ch in text if ch in "{}[]();=<>:") / max(len(text), 1)
        if density > 0.05:
            return True
        lines = text.splitlines()
        if lines:
            indent_ratio = sum(1 for ln in lines if ln.startswith((" ", "\t"))) / len(lines)
            if indent_ratio > 0.3:
                return True
        return False

    # ---- 各类格式化 ----
    def format_code_block(self, code: str, lang: Optional[str] = None) -> str:
        code = self._sanitize(code) if self.security_checks_enabled else code
        detected = lang or self._detect_language(code)
        if detected not in SUPPORTED_LANGUAGES:
            detected = "text"
        code = self._truncate_code(code)
        out = f"```{detected}\n{code.strip()}\n```"
        if self.log_output:
            h = hashlib.sha256(out.encode()).hexdigest()[:8]
            log.info(f"格式化代码输出(语言:{detected}, 哈希:{h})")
        return out

    def format_text(self, text: str) -> str:
        text = self._sanitize(text) if self.security_checks_enabled else text
        wrapped = textwrap.fill(text, width=100, replace_whitespace=False, drop_whitespace=True)
        if self.log_output:
            h = hashlib.sha256(text.encode()).hexdigest()[:8]
            log.info(f"格式化文本输出(哈希:{h})")
        return wrapped

    def format_table(self, data: Dict[str, Any]) -> str:
        if not data:
            return self.format_text("(空表)")
        max_len = max(len(v) if isinstance(v, list) else 1 for v in data.values())
        headers = list(data.keys())

        rows: List[List[str]] = []
        for i in range(max_len):
            row: List[str] = []
            for header in headers:
                value = data[header]
                if isinstance(value, list):
                    row.append(str(value[i]) if i < len(value) else "")
                else:
                    row.append(str(value) if i == 0 else "")
            rows.append(row)

        col_widths: List[int] = []
        for idx, header in enumerate(headers):
            width = len(header)
            for r in rows:
                width = max(width, len(r[idx]))
            col_widths.append(width)

        table = []
        head = "| " + " | ".join(h.ljust(w) for h, w in zip(headers, col_widths)) + " |"
        sep = "|-" + "-|-".join("-" * w for w in col_widths) + "-|"
        table.append(head)
        table.append(sep)
        for r in rows:
            table.append("| " + " | ".join(c.ljust(w) for c, w in zip(r, col_widths)) + " |")
        return "\n".join(table)

    def format_output(self, content: Any, lang: Optional[str] = None) -> str:
        if isinstance(content, str):
            return self.format_code_block(content, lang) if self.is_code(content) else self.format_text(content)
        if isinstance(content, dict):
            try:
                return self.format_table(content)
            except Exception as e:
                log.warning(f"表格格式化失败: {e}，回退到文本")
                return self.format_text(json.dumps(content, ensure_ascii=False, indent=2))
        if isinstance(content, (list, tuple)):
            return self.format_text("\n".join(f"- {i}" for i in content))
        return self.format_text(str(content))

    def format_error(self, error: Exception | str) -> str:
        if not isinstance(error, Exception):
            class _StrErr(Exception):
                ...
            error = _StrErr(str(error))

        etype = type(error).__name__
        emsg = str(error)
        box = [
            "╔" + "═" * 78 + "╗",
            f"║ {'ERROR':^76} ║",
            "╠" + "═" * 78 + "╣",
            f"║ {etype:76} ║",
            "╠" + "─" * 78 + "╣",
        ]
        for line in textwrap.wrap(emsg, width=76):
            box.append(f"║ {line:<76} ║")
        box.append("╚" + "═" * 78 + "╝")
        return "\n".join(box)

    def format_file(self, file_path: str) -> str:
        try:
            if not os.path.exists(file_path):
                return self.format_error(FileNotFoundError(f"文件不存在: {file_path}"))
            size = os.path.getsize(file_path)
            if size > MAX_OUTPUT_SIZE:
                return self.format_output(f"文件过大({size} bytes)，无法预览。")
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            _, ext = os.path.splitext(file_path)
            lang = ext[1:] if ext else None
            return self.format_code_block(content, lang)
        except Exception as e:
            return self.format_error(e)

# --------------------------
# 模块封装
# --------------------------
class FormatManagerModule(BaseModule):
    VERSION = "1.0.2"

    def __init__(self, meta=None, context=None):
        super().__init__(meta, context)
        self.core = FormatManagerCore()
        self._registered = False
        mod_name = getattr(self.meta, "name", "format_manager")
        log.info(f"{mod_name} v{self.VERSION} 初始化完成")

    # 必须实现：事件处理（事件总线会调用这里）
    def handle_event(self, event, *args, **kwargs):
        """
        统一事件入口：
        - 支持 event 为字符串（事件名）或对象（含 name/data）
        - 识别三类：format.output / format.error / format.file
        """
        try:
            if hasattr(event, "name"):
                name = getattr(event, "name", "") or ""
                data = getattr(event, "data", {}) or {}
            elif isinstance(event, dict):
                name = event.get("name", "") or ""
                data = event.get("data", {}) or {}
            else:
                name = str(event or "")
                data = kwargs.get("data", {}) or {}

            log.debug(f"handle_event 收到事件: {name}, data={str(data)[:200]}")

            if name == "format.output":
                content = data.get("content", "")
                lang = data.get("lang")
                disable_security = data.get("disable_security", False)
                log_output = data.get("log_output", False)
                self.core.enable_security_checks(not disable_security)
                self.core.set_log_output(log_output)
                result = self.core.format_output(content, lang)
                if getattr(self.context, "event_bus", None):
                    self.context.event_bus.publish("format.output.done", {"result": result})
                return result

            if name == "format.error":
                err = data.get("error", "未知错误")
                result = self.core.format_error(err)
                if getattr(self.context, "event_bus", None):
                    self.context.event_bus.publish("format.error.done", {"result": result})
                return result

            if name == "format.file":
                path = data.get("file_path")
                result = self.core.format_file(path) if path else self.core.format_output("⚠️ 参数 file_path 不能为空")
                if getattr(self.context, "event_bus", None):
                    self.context.event_bus.publish("format.file.done", {"result": result})
                return result

            log.debug(f"handle_event 忽略未识别事件: {name}")
            return None

        except Exception as e:
            log.error(f"handle_event 处理异常: {e}")
            return self.core.format_error(e)

    # 生命周期
    def preload(self):
        self._register_actions()
        if getattr(self.context, "event_bus", None):
            self.context.event_bus.subscribe("format.output", self.handle_event)
            self.context.event_bus.subscribe("format.error", self.handle_event)
            self.context.event_bus.subscribe("format.file", self.handle_event)
        log.info("format_manager preload 完成")

    def setup(self):
        self._register_actions()
        log.info("format_manager setup 完成")

    def start(self):
        log.info("format_manager 启动完成")

    def stop(self):
        log.info("format_manager 停止")

    def cleanup(self):
        log.info("format_manager 清理完成")

    def health_check(self) -> Dict[str, Any]:
        return {
            "status": "OK",
            "module": getattr(self.meta, "name", "format_manager"),
            "version": self.VERSION,
        }

    # --- 动作实现（标准签名：context=None, params=None, **kwargs）---
    def action_format_output(self, context=None, params=None, **kwargs) -> str:
        params = params or {}
        content = params.get("content", "")
        lang = params.get("lang")
        disable_security = params.get("disable_security", False)
        log_output = params.get("log_output", False)

        self.core.enable_security_checks(not disable_security)
        self.core.set_log_output(log_output)

        if not content:
            return self.core.format_output("⚠️ 参数 content 不能为空", "text")
        return self.core.format_output(content, lang)

    def action_format_error(self, context=None, params=None, **kwargs) -> str:
        params = params or {}
        err = params.get("error")
        if err is None:
            return self.core.format_output("⚠️ 参数 error 不能为空", "text")
        return self.core.format_error(err)

    def action_format_file(self, context=None, params=None, **kwargs) -> str:
        params = params or {}
        path = params.get("file_path")
        if not path:
            return self.core.format_output("⚠️ 参数 file_path 不能为空", "text")
        return self.core.format_file(path)

    # --- 注册动作 ---
    def _register_actions(self):
        if self._registered:
            return
        ACTION_MANAGER.register_action(
            name="format_output",
            func=self.action_format_output,
            description="格式化输出（代码/文本/表格/列表/其他）",
            permission="user",
            module="format_manager",
        )
        ACTION_MANAGER.register_action(
            name="format_error",
            func=self.action_format_error,
            description="格式化错误信息到装饰框",
            permission="user",
            module="format_manager",
        )
        ACTION_MANAGER.register_action(
            name="format_file",
            func=self.action_format_file,
            description="读取并格式化文件内容为代码块",
            permission="user",
            module="format_manager",
        )
        self._registered = True
        log.info("format_manager 动作已注册: ['format_output', 'format_error', 'format_file']")


# ==== 热插拔脚手架（可被 ModuleManager 调用） ====
def register_actions(dispatcher, context=None):
    meta_getter = getattr(dispatcher, "get_module_meta", None)
    meta = meta_getter("format_manager") if callable(meta_getter) else None
    mod = FormatManagerModule(meta=meta, context=context)

    dispatcher.register_action(
        name="format_output",
        func=mod.action_format_output,
        description="格式化输出（代码/文本/表格/列表/其他）",
        permission="user",
        module="format_manager",
    )
    dispatcher.register_action(
        name="format_error",
        func=mod.action_format_error,
        description="格式化错误信息到装饰框",
        permission="user",
        module="format_manager",
    )
    dispatcher.register_action(
        name="format_file",
        func=mod.action_format_file,
        description="读取并格式化文件内容为代码块",
        permission="user",
        module="format_manager",
    )
    log.info("register_actions: format_manager 动作注册完成")


# ==== 模块元数据（如未使用外置 manifest.json，可让主控发现） ====
MODULE_METADATA = {
    "name": "format_manager",
    "version": FormatManagerModule.VERSION,
    "description": "统一格式化输出（代码/文本/表格/错误/文件），带安全清洗与截断。",
    "author": "三花聚顶开发团队",
    "entry": "modules.format_manager",
    "actions": [
        {"name": "format_output", "description": "格式化输出", "permission": "user"},
        {"name": "format_error", "description": "格式化错误信息", "permission": "user"},
        {"name": "format_file", "description": "格式化文件内容", "permission": "user"},
    ],
    "dependencies": [],
    "config_schema": {},
}

MODULE_CLASS = FormatManagerModule

if __name__ == "__main__":
    core = FormatManagerCore()
    print(core.format_output("def hi():\n    print('hello')\n"))
    print(core.format_output("这是一段很长的中文文本，用于测试自动换行功能。" * 3))
    print(core.format_output({"Name": ["Alice", "Bob"], "Age": [18, 20], "Role": ["Dev", "PM"]}))
    try:
        1 / 0
    except Exception as e:
        print(core.format_error(e))
