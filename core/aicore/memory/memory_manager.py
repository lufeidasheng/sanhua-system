import json
import os
import time
from typing import Dict, List, Any, Optional, Callable, Set

class MemoryManager:
    CURRENT_VERSION = 2.0

    def __init__(self, memory_file="memory_data.json", auto_save=True):
        self.memory_file = memory_file
        self.auto_save = auto_save
        self.memory = self._init_empty_memory()
        self._load_memory()

    def _init_empty_memory(self) -> Dict[str, Any]:
        return {
            "version": self.CURRENT_VERSION,
            "metadata": {
                "created": time.time(),
                "last_modified": time.time(),
                "tags": set(),
                "external_refs": []
            },
            "preferences": [],
            "skills": [],
            "events": [],
            "notes": []
        }

    def _load_memory(self):
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    self.memory = self._init_empty_memory()
                    self.memory["notes"] = data
                    self._upgrade_memory_format()
                    print(f"⚠️ 旧版记忆格式，已升级到 v{self.CURRENT_VERSION}")
                else:
                    self.memory = data
                    file_version = data.get("version", 1.0)
                    if file_version < self.CURRENT_VERSION:
                        self._upgrade_memory_format()
                        print(f"🔄 记忆数据已从 v{file_version} 升级到 v{self.CURRENT_VERSION}")
                self._ensure_timestamps()
            except Exception as e:
                print(f"❌ 加载记忆失败: {e}")
                self.memory = self._init_empty_memory()
                self._save_memory()
        else:
            self._save_memory()

    def _upgrade_memory_format(self):
        if "metadata" not in self.memory:
            self.memory["metadata"] = {
                "created": time.time(),
                "last_modified": time.time(),
                "tags": set(),
                "external_refs": []
            }
        self._ensure_timestamps()
        self.memory["version"] = self.CURRENT_VERSION
        self._save_memory()

    def _ensure_timestamps(self):
        for category in self.get_supported_categories():
            for i, item in enumerate(self.memory.get(category, [])):
                if not isinstance(item, dict) or "timestamp" not in item:
                    self.memory[category][i] = {
                        "content": item,
                        "timestamp": time.time(),
                        "source": "legacy"
                    }

    def _save_memory(self):
        try:
            self.memory["metadata"]["last_modified"] = time.time()
            # sets/objects不能直接json，需要序列化
            meta = self.memory.get("metadata", {})
            if "tags" in meta and isinstance(meta["tags"], set):
                meta["tags"] = list(meta["tags"])
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(self.memory, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"❌ 保存记忆失败: {e}")
            return False

    def save_memory(self):
        return self._save_memory()

    # ==== 对外核心功能 ====
    def absorb_memory(self, data: Dict[str, List[Any]], overwrite=False):
        for category, items in data.items():
            if category not in self.memory:
                self.memory[category] = []
            if overwrite:
                self.memory[category] = []
            for item in items:
                self._add_item(category, item)
        if self.auto_save:
            self.save_memory()

    def _add_item(self, category: str, item: Any):
        if category not in self.memory:
            self.memory[category] = []
        entry = item if isinstance(item, dict) else {
            "content": item,
            "timestamp": time.time(),
            "source": "user"
        }
        if not self._is_duplicate(category, entry):
            self.memory[category].append(entry)
            return True
        return False

    def _is_duplicate(self, category: str, item: Any) -> bool:
        if category not in self.memory:
            return False
        content = item.get("content") if isinstance(item, dict) and "content" in item else item
        for entry in self.memory[category]:
            existing_content = entry.get("content") if isinstance(entry, dict) and "content" in entry else entry
            if existing_content == content:
                return True
        return False

    def query_category(self, category: str, filter_func: Optional[Callable] = None) -> List[Any]:
        if category not in self.memory:
            return []
        if filter_func:
            return [item for item in self.memory[category] if filter_func(item)]
        return self.memory[category]

    def query_all(self) -> Dict[str, Any]:
        return self.memory

    def search(self, keyword: str, categories: Optional[List[str]] = None) -> Dict[str, List[Any]]:
        results = {}
        search_categories = categories or self.get_supported_categories()
        for category in search_categories:
            if category not in self.memory:
                continue
            matches = []
            for item in self.memory[category]:
                content = item.get("content") if isinstance(item, dict) and "content" in item else str(item)
                if keyword.lower() in content.lower():
                    matches.append(item)
            if matches:
                results[category] = matches
        return results

    def add_to_category(self, category: str, item: Any, allow_duplicate=False) -> bool:
        if allow_duplicate:
            return self._add_item(category, item)
        else:
            content = item.get("content") if isinstance(item, dict) and "content" in item else item
            if not self._is_duplicate(category, content):
                return self._add_item(category, item)
            return False

    def remove_from_category(self, category: str, item: Any) -> bool:
        if category not in self.memory:
            return False
        content_to_remove = item.get("content") if isinstance(item, dict) and "content" in item else item
        for i, entry in enumerate(self.memory[category]):
            existing_content = entry.get("content") if isinstance(entry, dict) and "content" in entry else entry
            if existing_content == content_to_remove:
                del self.memory[category][i]
                if self.auto_save:
                    self.save_memory()
                return True
        return False

    def clear_category(self, category: str) -> bool:
        if category in self.memory and category not in ["version", "metadata"]:
            self.memory[category] = []
            if self.auto_save:
                self.save_memory()
            return True
        return False

    def cleanup(self, max_age_days: int = 180, preserve_categories: List[str] = ["skills", "preferences"]):
        current_time = time.time()
        threshold = max_age_days * 24 * 60 * 60
        for category in self.get_supported_categories():
            if category in preserve_categories:
                continue
            self.memory[category] = [
                item for item in self.memory[category]
                if current_time - item.get("timestamp", 0) <= threshold
            ]
        if self.auto_save:
            self.save_memory()

    def export_memory(self, path: str, category: Optional[str] = None, include_metadata: bool = True):
        try:
            if category:
                data = {category: self.memory.get(category, [])}
            else:
                data = self.memory.copy()
                if not include_metadata:
                    data.pop("metadata", None)
                    data.pop("version", None)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"✅ 成功导出记忆到 {path}")
            return True
        except Exception as e:
            print(f"❌ 导出记忆失败: {e}")
            return False

    def import_memory(self, path: str, merge: bool = True, overwrite: bool = False):
        if not os.path.exists(path):
            print(f"❌ 导入文件不存在: {path}")
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not merge:
                self.memory = self._init_empty_memory()
                self.absorb_memory(data, overwrite=True)
            else:
                self.absorb_memory(data, overwrite=overwrite)
            print(f"✅ 成功从 {path} 导入记忆")
            return True
        except Exception as e:
            print(f"❌ 导入记忆失败: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        stats = {
            "total_categories": 0,
            "total_items": 0,
            "category_counts": {}
        }
        for category, items in self.memory.items():
            if category in ["version", "metadata"]:
                continue
            if isinstance(items, list):
                stats["total_items"] += len(items)
                stats["category_counts"][category] = len(items)
                stats["total_categories"] += 1
        stats["created"] = self.memory.get("metadata", {}).get("created", 0)
        stats["last_modified"] = self.memory.get("metadata", {}).get("last_modified", 0)
        return stats

    # ==== 新增自描述/发现能力 ====
    def get_supported_categories(self) -> List[str]:
        # 自动返回除系统字段外所有类别
        return [cat for cat in self.memory.keys() if cat not in ["version", "metadata"]]

    def get_metadata(self, category: Optional[str] = None) -> Any:
        if not category:
            return self.memory.get("metadata", {})
        return {"count": len(self.memory.get(category, [])),
                "example": self.memory.get(category, [None])[0]}

    def describe(self) -> str:
        """简要描述本记忆模块（可被主控或AI系统发现）"""
        return f"MemoryManager v{self.CURRENT_VERSION}, 支持类别: {', '.join(self.get_supported_categories())}"

# ====== 简易单元测试（开发期可删除）======
if __name__ == "__main__":
    mm = MemoryManager(auto_save=True)
    print("🧠", mm.describe())
    mm.add_to_category("notes", "三花聚顶初版上线！")
    print("📒 notes:", mm.query_category("notes"))
    print("全部统计：", mm.get_stats())
