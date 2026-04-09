import os
import json
import hashlib
from typing import Dict, List, Any, Optional

from core.core2_0.sanhuatongyu.logger import get_logger

class ModuleMeta:
    """
    三花聚顶 · 标准模块元数据对象

    用于描述和管理单个功能模块的基本信息、依赖关系、权限声明等，支持指纹溯源和安全校验。
    """

    def __init__(self, name: str, path: str, manifest: Dict[str, Any]):
        self.logger = get_logger(f'module_meta.{name}')
        self.name: str = name
        self.path: str = path
        self.version: str = manifest.get('version', '1.0.0')
        self.entry_points: List[str] = manifest.get('entry_points', [])
        self.visibility: str = manifest.get('visibility', 'interface')
        self.enabled: bool = manifest.get('enabled', True)
        self.debug_only: bool = manifest.get('debug_only', False)
        self.dependencies: List[str] = manifest.get('dependencies', [])
        self.required_permissions: List[str] = manifest.get('permissions', [])
        self.config_schema: Dict[str, Any] = manifest.get('config_schema', {})
        self.description: str = manifest.get('description', '')
        self.fingerprint: str = self._calculate_fingerprint()

    def _calculate_fingerprint(self) -> str:
        """
        计算模块的唯一指纹（哈希值），用于热加载校验和完整性溯源。
        指纹包含 .py 源码和 manifest.json 文件内容。
        """
        hasher = hashlib.sha256()
        try:
            if not os.path.isdir(self.path):
                self.logger.warning(
                    "fingerprint_path_not_found",
                    path=self.path
                )
                return ""
            for root, _, files in os.walk(self.path):
                for file in sorted(files):
                    if file.endswith('.py') or file == 'manifest.json':
                        file_path = os.path.join(root, file)
                        try:
                            with open(file_path, 'rb') as f:
                                hasher.update(f.read())
                        except Exception as e:
                            self.logger.warning(
                                "fingerprint_file_read_failed",
                                file=file_path,
                                error=str(e)
                            )
            return hasher.hexdigest()
        except Exception as e:
            self.logger.error("fingerprint_calculation_failed", error=str(e))
            return ""

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典结构，便于序列化和对外输出。
        """
        return {
            "name": self.name,
            "path": self.path,
            "version": self.version,
            "entry_points": self.entry_points,
            "visibility": self.visibility,
            "enabled": self.enabled,
            "debug_only": self.debug_only,
            "dependencies": self.dependencies,
            "permissions": self.required_permissions,
            "config_schema": self.config_schema,
            "description": self.description,
            "fingerprint": self.fingerprint,
        }

    def has_permission(self, permission: str) -> bool:
        """
        判断当前模块声明了指定权限（推荐模块依赖/事件权限校验时调用）
        """
        return permission in self.required_permissions

    def reload_manifest(self) -> bool:
        """
        支持在模块热更新/manifest变更时，重新加载元数据和刷新指纹。
        """
        manifest_path = os.path.join(self.path, 'manifest.json')
        try:
            if not os.path.isfile(manifest_path):
                self.logger.warning("manifest_file_missing", file=manifest_path)
                return False
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
            # 动态刷新各字段
            self.version = manifest.get('version', self.version)
            self.entry_points = manifest.get('entry_points', self.entry_points)
            self.visibility = manifest.get('visibility', self.visibility)
            self.enabled = manifest.get('enabled', self.enabled)
            self.debug_only = manifest.get('debug_only', self.debug_only)
            self.dependencies = manifest.get('dependencies', self.dependencies)
            self.required_permissions = manifest.get('permissions', self.required_permissions)
            self.config_schema = manifest.get('config_schema', self.config_schema)
            self.description = manifest.get('description', self.description)
            self.fingerprint = self._calculate_fingerprint()
            self.logger.info("manifest_reloaded", module=self.name, version=self.version)
            return True
        except Exception as e:
            self.logger.error("manifest_reload_failed", module=self.name, error=str(e))
            return False

    def __repr__(self) -> str:
        return f"<ModuleMeta name={self.name} version={self.version} path={self.path} enabled={self.enabled}>"
