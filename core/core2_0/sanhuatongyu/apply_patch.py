#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import difflib
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.core2_0.sanhuatongyu.rollback_manager import RollbackManager


@dataclass
class PatchOperation:
    path: str
    op: str  # replace_text / append_text / write_text
    old: Optional[str] = None
    new: Optional[str] = None
    text: Optional[str] = None
    occurrence: int = 1
    encoding: str = "utf-8"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ApplyPatchResult:
    ok: bool
    dry_run: bool
    snapshot_id: Optional[str]
    rolled_back: bool
    results: List[Dict[str, Any]] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ApplyPatchEngine:
    """
    正式写盘执行器（第一版）：
    - replace_text
    - append_text
    - write_text
    - 改前自动快照
    - 异常时自动回滚
    """

    def __init__(
        self,
        root: Optional[str] = None,
        rollback_manager: Optional[RollbackManager] = None,
    ) -> None:
        self.root = Path(root).resolve() if root else Path.cwd().resolve()
        self.rollback_manager = rollback_manager or RollbackManager(root=str(self.root))

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------

    def apply_changes(
        self,
        operations: List[Dict[str, Any]],
        *,
        reason: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
    ) -> ApplyPatchResult:
        normalized_ops = [self._normalize_op(x) for x in operations]
        unique_paths = self._unique_paths(normalized_ops)

        snapshot_id: Optional[str] = None
        rolled_back = False
        out: List[Dict[str, Any]] = []

        if not dry_run:
            snapshot = self.rollback_manager.create_snapshot(
                unique_paths,
                reason=reason or "apply_patch",
                metadata=metadata or {},
            )
            snapshot_id = snapshot.snapshot_id

        try:
            for op in normalized_ops:
                ok, result, final_text = self._apply_one(op, dry_run=dry_run)
                out.append(result)

                if not ok:
                    if snapshot_id and not dry_run:
                        self.rollback_manager.rollback(snapshot_id)
                        rolled_back = True
                    return ApplyPatchResult(
                        ok=False,
                        dry_run=dry_run,
                        snapshot_id=snapshot_id,
                        rolled_back=rolled_back,
                        results=out,
                        reason=str(result.get("reason") or "apply_failed"),
                    )

                if not dry_run:
                    p = self._resolve_path(op.path)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(final_text, encoding=op.encoding)

            return ApplyPatchResult(
                ok=True,
                dry_run=dry_run,
                snapshot_id=snapshot_id,
                rolled_back=False,
                results=out,
                reason="ok",
            )

        except Exception as exc:
            if snapshot_id and not dry_run:
                self.rollback_manager.rollback(snapshot_id)
                rolled_back = True

            out.append(
                {
                    "status": "failed",
                    "reason": str(exc),
                }
            )
            return ApplyPatchResult(
                ok=False,
                dry_run=dry_run,
                snapshot_id=snapshot_id,
                rolled_back=rolled_back,
                results=out,
                reason=str(exc),
            )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _normalize_op(self, raw: Dict[str, Any]) -> PatchOperation:
        if isinstance(raw, PatchOperation):
            return raw
        return PatchOperation(
            path=str(raw["path"]),
            op=str(raw["op"]),
            old=raw.get("old"),
            new=raw.get("new"),
            text=raw.get("text"),
            occurrence=int(raw.get("occurrence", 1) or 1),
            encoding=str(raw.get("encoding", "utf-8")),
        )

    def _unique_paths(self, ops: List[PatchOperation]) -> List[str]:
        seen = set()
        out = []
        for op in ops:
            if op.path not in seen:
                out.append(op.path)
                seen.add(op.path)
        return out

    def _resolve_path(self, raw_path: str) -> Path:
        p = Path(raw_path)
        if not p.is_absolute():
            p = self.root / p
        return p.resolve()

    def _apply_one(self, op: PatchOperation, *, dry_run: bool) -> Tuple[bool, Dict[str, Any], str]:
        p = self._resolve_path(op.path)
        before = ""
        existed_before = p.exists()

        if existed_before:
            before = p.read_text(encoding=op.encoding)

        if op.op == "replace_text":
            ok, after, detail = self._replace_text(before, op)
        elif op.op == "append_text":
            ok, after, detail = self._append_text(before, op)
        elif op.op == "write_text":
            ok, after, detail = self._write_text(op)
        else:
            return False, {
                "path": str(p),
                "op": op.op,
                "status": "failed",
                "reason": "unsupported_op",
            }, before

        diff_preview = self._build_diff_preview(str(p), before, after)
        result = {
            "path": str(p),
            "op": op.op,
            "status": "ok" if ok else "failed",
            "dry_run": dry_run,
            "existed_before": existed_before,
            "changed": before != after,
            "diff_preview": diff_preview,
            "diff_truncated": False,
        }
        result.update(detail)
        return ok, result, after

    def _replace_text(self, before: str, op: PatchOperation) -> Tuple[bool, str, Dict[str, Any]]:
        if op.old is None or op.new is None:
            return False, before, {"reason": "old_or_new_missing"}

        match_count = before.count(op.old)
        if match_count <= 0:
            return False, before, {
                "reason": "pattern_not_found",
                "match_count": 0,
            }

        occurrence = max(int(op.occurrence or 1), 1)
        if occurrence > match_count:
            return False, before, {
                "reason": "occurrence_out_of_range",
                "match_count": match_count,
                "occurrence": occurrence,
            }

        after = self._replace_nth(before, op.old, op.new, occurrence)
        return True, after, {
            "reason": None,
            "match_count": match_count,
            "replace_count": 1,
            "occurrence": occurrence,
        }

    def _append_text(self, before: str, op: PatchOperation) -> Tuple[bool, str, Dict[str, Any]]:
        if op.text is None:
            return False, before, {"reason": "text_missing"}
        after = before + op.text
        return True, after, {
            "reason": None,
            "appended_chars": len(op.text),
        }

    def _write_text(self, op: PatchOperation) -> Tuple[bool, str, Dict[str, Any]]:
        if op.text is None:
            return False, "", {"reason": "text_missing"}
        return True, op.text, {
            "reason": None,
            "written_chars": len(op.text),
        }

    def _replace_nth(self, text: str, old: str, new: str, occurrence: int) -> str:
        start = 0
        current = 0
        while True:
            idx = text.find(old, start)
            if idx < 0:
                return text
            current += 1
            if current == occurrence:
                return text[:idx] + new + text[idx + len(old):]
            start = idx + len(old)

    def _build_diff_preview(self, path: str, before: str, after: str) -> str:
        before_lines = before.splitlines(True)
        after_lines = after.splitlines(True)
        diff = difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile="{} (before)".format(path),
            tofile="{} (after)".format(path),
            lineterm="",
        )
        return "".join(diff)
