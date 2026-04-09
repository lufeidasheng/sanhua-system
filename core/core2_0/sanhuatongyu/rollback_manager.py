#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class SnapshotFileRecord:
    path: str
    abs_path: str
    existed_before: bool
    backup_relpath: Optional[str] = None
    size: int = 0
    sha256: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SnapshotRecord:
    snapshot_id: str
    root: str
    created_at: int
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    files: List[SnapshotFileRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "root": self.root,
            "created_at": self.created_at,
            "reason": self.reason,
            "metadata": self.metadata,
            "files": [f.to_dict() for f in self.files],
        }


class RollbackManager:
    """
    回滚管理器：
    1. 修改前做快照
    2. 修改失败时恢复
    3. 保留 manifest 方便审计
    """

    def __init__(self, root: Optional[str] = None, base_dir: Optional[str] = None) -> None:
        self.root = Path(root).resolve() if root else Path.cwd().resolve()
        if base_dir:
            self.base_dir = Path(base_dir).resolve()
        else:
            self.base_dir = self.root / "audit_output" / "rollback_snapshots_runtime"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------

    def create_snapshot(
        self,
        paths: List[str],
        *,
        reason: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SnapshotRecord:
        snapshot_id = self._new_snapshot_id()
        snapshot_dir = self.base_dir / snapshot_id
        files_dir = snapshot_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)

        record = SnapshotRecord(
            snapshot_id=snapshot_id,
            root=str(self.root),
            created_at=int(time.time()),
            reason=reason,
            metadata=metadata or {},
            files=[],
        )

        for raw_path in paths:
            abs_path = self._resolve_path(raw_path)
            rel_backup = self._backup_relpath(abs_path)
            target_backup = files_dir / rel_backup
            target_backup.parent.mkdir(parents=True, exist_ok=True)

            existed_before = abs_path.exists()
            file_record = SnapshotFileRecord(
                path=str(raw_path),
                abs_path=str(abs_path),
                existed_before=existed_before,
                backup_relpath=str(rel_backup) if existed_before else None,
            )

            try:
                if existed_before:
                    if abs_path.is_file():
                        shutil.copy2(abs_path, target_backup)
                        file_record.size = abs_path.stat().st_size
                        file_record.sha256 = self._sha256_file(abs_path)
                    else:
                        file_record.error = "not_a_file"
                record.files.append(file_record)
            except Exception as exc:
                file_record.error = str(exc)
                record.files.append(file_record)

        self._write_manifest(snapshot_dir, record)
        return record

    def rollback(self, snapshot_id: str) -> Dict[str, Any]:
        snapshot_dir = self.base_dir / snapshot_id
        manifest_path = snapshot_dir / "manifest.json"

        if not manifest_path.exists():
            return {
                "ok": False,
                "snapshot_id": snapshot_id,
                "reason": "manifest_not_found",
            }

        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {
                "ok": False,
                "snapshot_id": snapshot_id,
                "reason": f"manifest_read_failed: {exc}",
            }

        restored = []
        removed = []
        failed = []

        files_dir = snapshot_dir / "files"
        for item in data.get("files", []):
            abs_path = Path(item["abs_path"])
            existed_before = bool(item.get("existed_before"))
            backup_relpath = item.get("backup_relpath")

            try:
                abs_path.parent.mkdir(parents=True, exist_ok=True)

                if existed_before:
                    if not backup_relpath:
                        failed.append({"path": str(abs_path), "reason": "backup_relpath_missing"})
                        continue
                    backup_file = files_dir / backup_relpath
                    if not backup_file.exists():
                        failed.append({"path": str(abs_path), "reason": "backup_file_missing"})
                        continue
                    shutil.copy2(backup_file, abs_path)
                    restored.append(str(abs_path))
                else:
                    if abs_path.exists():
                        if abs_path.is_file():
                            abs_path.unlink()
                            removed.append(str(abs_path))
                        else:
                            failed.append({"path": str(abs_path), "reason": "target_is_not_file"})
            except Exception as exc:
                failed.append({"path": str(abs_path), "reason": str(exc)})

        return {
            "ok": len(failed) == 0,
            "snapshot_id": snapshot_id,
            "restored": restored,
            "removed": removed,
            "failed": failed,
        }

    def list_snapshots(self, limit: int = 20) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for manifest_path in sorted(self.base_dir.glob("*/manifest.json"), reverse=True):
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                items.append(
                    {
                        "snapshot_id": data.get("snapshot_id"),
                        "created_at": data.get("created_at"),
                        "reason": data.get("reason", ""),
                        "file_count": len(data.get("files", [])),
                    }
                )
            except Exception:
                continue
            if len(items) >= limit:
                break
        return items

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _new_snapshot_id(self) -> str:
        return "snap-{}-{}".format(time.strftime("%Y%m%d_%H%M%S"), uuid.uuid4().hex[:8])

    def _resolve_path(self, raw_path: str) -> Path:
        p = Path(raw_path)
        if not p.is_absolute():
            p = self.root / p
        return p.resolve()

    def _backup_relpath(self, abs_path: Path) -> Path:
        try:
            rel = abs_path.relative_to(self.root)
            return rel
        except Exception:
            digest = hashlib.sha1(str(abs_path).encode("utf-8")).hexdigest()[:12]
            return Path("_external") / "{}__{}".format(digest, abs_path.name)

    def _write_manifest(self, snapshot_dir: Path, record: SnapshotRecord) -> None:
        manifest_path = snapshot_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _sha256_file(self, path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
