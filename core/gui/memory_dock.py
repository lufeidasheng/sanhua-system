# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import time
from typing import Any, Dict, List

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
    记忆中心 Dock：
    - 依赖的 memory_manager 只需要实现:
      - get_all() -> 任意结构（本类会做归一化）
      - add_to_category(name: str, item: dict)
      - clear_all()  (可选，没有则用兜底方案清空 _data 并保存)
      - export_all() (可选，用于导出原始结构)
    """

    def __init__(self, memory_manager, parent=None):
        super().__init__("🧠 记忆中心", parent)
        self.memory = memory_manager

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

    # ================ 刷新展示 ================

    def refresh(self):
        """刷新 GUI 列表，展示当前所有记忆（已扁平化）"""
        self.list.clear()

        try:
            # 优先用 get_all，兼容我们新 MemoryManager 的扁平接口
            if hasattr(self.memory, "get_all"):
                raw = self.memory.get_all()
            elif hasattr(self.memory, "export_all"):
                raw = self.memory.export_all()
            else:
                raw = []
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
            # 优先尊重 MemoryManager 的原始结构
            if hasattr(self.memory, "export_all"):
                payload = self.memory.export_all()
            else:
                # 从扁平视图倒推回 {category: [items...]}
                raw = self.memory.get_all() if hasattr(self.memory, "get_all") else []
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
                        self.memory.add_to_category(cat, e)
            elif isinstance(data, list):
                for e in data:
                    self.memory.add_to_category("default", e)
            else:
                self.memory.add_to_category("default", {"value": data})

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

        try:
            if hasattr(self.memory, "clear_all") and callable(self.memory.clear_all):
                self.memory.clear_all()
            else:
                # 兜底：直接清空内部数据并保存（仅在 MemoryManager 是我们那种实现时生效）
                if hasattr(self.memory, "_data"):
                    self.memory._data.clear()  # type: ignore[attr-defined]
                if hasattr(self.memory, "_save") and callable(self.memory._save):
                    self.memory._save()  # type: ignore[attr-defined]

            self.refresh()
            self.label.setText("🧹 已清空所有记忆")

        except Exception as e:
            QMessageBox.critical(self, "清除失败", f"清空记忆时发生错误：{e}")