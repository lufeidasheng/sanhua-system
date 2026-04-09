#!/usr/bin/env python3
"""
module_standardizer.py - 最终修正版模块标准化工具
"""

import os
import re
import json
import sys
import time
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import yaml

# === 默认配置 ===
DEFAULT_CONFIG = {
    "modules_dir": "modules",
    "log_level": "INFO",
    "required_files": ["__init__.py"],
    "exclude_dirs": ["__pycache__", ".git", "test"],
    "manifest": {
        "default_version": "1.0.0",
        "required_fields": ["id", "name", "version"]
    }
}

class ModuleStandardizer:
    def __init__(self, config: Dict, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run
        self.logger = self._init_logger()
        self.modules_dir = Path(config["modules_dir"]).resolve()
        self.stats = {
            "valid_modules": 0,
            "manifests_created": 0,
            "manifests_updated": 0,
            "start_time": time.time()
        }

    def _init_logger(self):
        logger = logging.getLogger("module_std")
        logger.setLevel(self.config["log_level"].upper())
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "[%(asctime)s %(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger

    def is_real_module(self, path: Path) -> bool:
        """严格验证是否为真实模块目录"""
        if not path.is_dir():
            return False
        
        # 排除隐藏目录和特殊目录
        if any(part.startswith(('.', '_')) for part in path.parts) or path.name in self.config["exclude_dirs"]:
            return False
            
        # 检查必需文件
        for req_file in self.config["required_files"]:
            if not (path / req_file).exists():
                return False
                
        # 必须包含至少一个非__init__.py的Python文件
        py_files = [f for f in path.glob("*.py") if f.name != "__init__.py"]
        return len(py_files) > 0

    def process_directory(self):
        """处理模块目录"""
        if not self.modules_dir.exists():
            self.logger.error(f"目录不存在: {self.modules_dir}")
            return False

        self.logger.info(f"开始处理目录: {self.modules_dir}")
        self.logger.info(f"模式: {'DRY-RUN' if self.dry_run else '实际执行'}")

        for module_dir in sorted(self.modules_dir.iterdir()):
            if not self.is_real_module(module_dir):
                continue

            self.stats["valid_modules"] += 1
            self.process_manifest(module_dir)

        elapsed = time.time() - self.stats["start_time"]
        self.logger.info(f"\n=== 处理完成 ===")
        self.logger.info(f"有效模块: {self.stats['valid_modules']}")
        self.logger.info(f"创建的 manifest: {self.stats['manifests_created']}")
        self.logger.info(f"更新的 manifest: {self.stats['manifests_updated']}")
        self.logger.info(f"耗时: {elapsed:.2f} 秒")

        return True

    def process_manifest(self, module_dir: Path):
        """处理 manifest 文件"""
        manifest_path = module_dir / "manifest.json"
        manifest = self.load_manifest(manifest_path)
        
        changed = False
        required_fields = self.config["manifest"]["required_fields"]
        
        if not manifest.get("id"):
            manifest["id"] = module_dir.name
            changed = True
            
        if not manifest.get("name"):
            manifest["name"] = module_dir.name.replace("_", " ").title()
            changed = True
            
        if not manifest.get("version"):
            manifest["version"] = self.config["manifest"]["default_version"]
            changed = True
            
        if changed:
            action = "创建" if not manifest_path.exists() else "更新"
            if self.dry_run:
                self.logger.info(f"[DRY-RUN] 将{action} manifest: {manifest_path}")
                return
                
            if not manifest_path.exists():
                self.stats["manifests_created"] += 1
            else:
                self.stats["manifests_updated"] += 1
                
            self.save_manifest(manifest_path, manifest)
            self.logger.info(f"已{action} manifest: {manifest_path}")

    def load_manifest(self, path: Path) -> Dict:
        """加载 manifest 文件"""
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.warning(f"加载 manifest 失败 {path}: {str(e)}")
        return {}

    def save_manifest(self, path: Path, data: Dict):
        """保存 manifest 文件"""
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"保存 manifest 失败 {path}: {str(e)}")

def main():
    parser = argparse.ArgumentParser(description="模块标准化工具")
    parser.add_argument("modules_dir", nargs="?", default=DEFAULT_CONFIG["modules_dir"], help="模块目录路径")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不修改文件")
    args = parser.parse_args()

    config = DEFAULT_CONFIG.copy()
    config["modules_dir"] = args.modules_dir

    standardizer = ModuleStandardizer(config, args.dry_run)
    standardizer.process_directory()

if __name__ == "__main__":
    main()
