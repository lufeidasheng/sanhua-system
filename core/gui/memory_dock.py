# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QListWidget,
    QPushButton,
    QLabel,
    QFileDialog,
    QMessageBox,
)


def _normalize_records(raw: Any) -> List[Dict[str, Any]]:
    """
    把各种可能的记忆结构统一打平成 List[dict]，每条至少有:
    - category: str
    - ts: float
    - 其他字段: 原样透传/兜底到 value
    """
    now = time.time()

    def _wrap_item(item: Any, category: str) -> Dict[str, Any]:
        if isinstance(item, dict):
            rec = dict(item)
        else:
            rec = {"value": item}

        # 分类兜底
        rec.setdefault("category", category)

        # 时间戳兜底
        ts = rec.get("ts")
        if not isinstance(ts, (int, float)):
            rec["ts"] = float(now)

        return rec

    # 顶层是 dict: {category: [items...] 或 item}
    if isinstance(raw, dict):
        out: List[Dict[str, Any]] = []
        for cat, items in raw.items():
            if isinstance(items, list):
                for it in items:
                    out.append(_wrap_item(it, str(cat)))
            else:
                out.append(_wrap_item(items, str(cat)))
        return out

    # 顶层是 list: [item1, item2, ...]，分类兜底 default 或 item 自带 category
    if isinstance(raw, list):
        out: List[Dict[str, Any]] = []
        for it in raw:
            if isinstance(it, dict):
                cat = str(it.get("category", "default"))
            else:
                cat = "default"
            out.append(_wrap_item(it, cat))
        return out

    # 其他奇怪类型，全部包成一条 default
    return [_wrap_item(raw, "default")]


class MemoryDock(QDockWidget):
    """
    记忆中心 Dock。

    构造参数保留 memory_manager 名称用于兼容旧调用；生产访问只走
    context.call_action(...) 标准动作入口。
    """

    def __init__(self, memory_manager, parent=None):
        super().__init__("🧠 记忆中心", parent)
        self.memory_context = self._resolve_context(memory_manager, parent)

        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        w = QWidget()
        layout = QVBoxLayout(w)

        self.label = QLabel("📚 当前记忆")
        self.list = QListWidget()

        btn_refresh = QPushButton("🔄 刷新记忆")
        btn_export = QPushButton("📤 导出为 JSON")
        btn_import = QPushButton("📥 导入 JSON")
        btn_clear = QPushButton("🧹 清空所有记忆（慎重）")

        layout.addWidget(self.label)
        layout.addWidget(self.list)
        layout.addWidget(btn_refresh)
        layout.addWidget(btn_export)
        layout.addWidget(btn_import)
        layout.addWidget(btn_clear)

        btn_refresh.clicked.connect(self.refresh)
        btn_export.clicked.connect(self.export_json)
        btn_import.clicked.connect(self.import_json)
        btn_clear.clicked.connect(self.clear_memory)

        self.setWidget(w)
        self.refresh()

    def _resolve_context(self, memory_manager: Any, parent: Any) -> Optional[Any]:
        candidates = [memory_manager, parent]
        for source in (memory_manager, parent):
            if source is None:
                continue
            candidates.append(getattr(source, "context", None))
            candidates.append(getattr(source, "ctx", None))

        for candidate in candidates:
            if candidate is not None and callable(getattr(candidate, "call_action", None)):
                return candidate

        return None

    def _call_memory_action(self, action: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if self.memory_context is None:
            return {"ok": False, "error": "memory context unavailable", "action": action}

        try:
            return self.memory_context.call_action(action, params=params or {})
        except Exception as e:
            return {"ok": False, "error": str(e), "action": action}

    def _snapshot_payload(self) -> Any:
        result = self._call_memory_action("memory.snapshot", {})
        if not isinstance(result, dict):
            return result

        data = result.get("data")
        if data is not None:
            return data

        for key in ("snapshot", "records", "items", "memories", "memory"):
            value = result.get(key)
            if value is not None:
                return value

        return result

    # ================ 刷新展示 ================

    def refresh(self):
        """刷新 GUI 列表，展示当前所有记忆（已扁平化）"""
        self.list.clear()

        try:
            raw = self._snapshot_payload()
            records = _normalize_records(raw)
        except Exception as e:
            self.label.setText(f"❌ 记忆加载失败: {e}")
            return

        for rec in records:
            category = rec.get("category", "default")

            # 内容优先级：title > summary > content > text > value
            text = (
                rec.get("title")
                or rec.get("summary")
                or rec.get("content")
                or rec.get("text")
                or rec.get("value")
                or ""
            )
            text = str(text)
            if len(text) > 80:
                text = text[:80] + "..."

            self.list.addItem(f"[{category}] {text}")

        self.label.setText(f"📚 当前记忆（{len(records)} 条）")

    # ================ 导出 ================

    def export_json(self):
        """把当前记忆导出为 JSON 文件"""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出记忆",
            "memory.json",
            "JSON Files (*.json)",
        )
        if not path:
            return

        try:
            raw = self._snapshot_payload()
            records = _normalize_records(raw)
            payload: Dict[str, List[Dict[str, Any]]] = {}
            for rec in records:
                cat = rec.get("category", "default")
                payload.setdefault(cat, []).append(rec)

            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            self.label.setText("✅ 记忆已导出")

        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"导出 JSON 时发生错误：{e}")

    # ================ 导入 ================

    def import_json(self):
        """从 JSON 文件导入记忆，并合并进当前 MemoryManager"""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入记忆",
            "",
            "JSON Files (*.json)",
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 支持两种主流格式：
            # 1) dict: {category: [items...]}
            # 2) list: [item1, item2, ...] -> 统归到 "default"
            if isinstance(data, dict):
                for cat, arr in data.items():
                    if not isinstance(arr, list):
                        arr = [arr]
                    for e in arr:
                        item = dict(e) if isinstance(e, dict) else {"value": e}
                        item.setdefault("category", str(cat))
                        self._call_memory_action("memory.add", item)
            elif isinstance(data, list):
                for e in data:
                    item = dict(e) if isinstance(e, dict) else {"value": e}
                    item.setdefault("category", "default")
                    self._call_memory_action("memory.add", item)
            else:
                self._call_memory_action("memory.add", {"category": "default", "value": data})

            self.refresh()
            self.label.setText("✅ 记忆已导入合并")

        except Exception as e:
            QMessageBox.critical(self, "导入失败", f"导入 JSON 时发生错误：{e}")

    # ================ 清空 ================

    def clear_memory(self):
        """清空所有记忆（慎用）"""
        ok = QMessageBox.question(
            self,
            "确认清除",
            "确定要清空所有记忆吗？此操作不可恢复！",
        )
        if ok != QMessageBox.StandardButton.Yes:
            return

        QMessageBox.information(
            self,
            "暂不支持",
            "当前没有已注册的标准记忆清空动作，已跳过清空操作。",
        )
        self.label.setText("⚠️ 当前不支持从 GUI 直接清空记忆")
