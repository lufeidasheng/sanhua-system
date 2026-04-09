import json
import os
import re
import time
import threading
import asyncio
from typing import List, Dict, Any, Union, Optional, Callable
from pathlib import Path
from core.core2_0.sanhuatongyu.logger import get_logger

log = get_logger(__name__)

# ====== 配置 ======
BASE_DIR = Path(__file__).parent.parent
MEMORY_FILE = BASE_DIR / "memory_data.json"
LOG_FILE = BASE_DIR / "memory_log.txt"

class MemoryEngine:
    """
    三花聚顶·MemoryEngine 记忆快存引擎
    支持键值对记忆、元数据、多标签、批量操作、事件触发、过期自动清理等
    """
    def __init__(self, memory_file: Union[str, Path] = MEMORY_FILE, log_file: Union[str, Path] = LOG_FILE):
        self.memory_file = Path(memory_file).resolve()
        self.log_file = Path(log_file).resolve()
        self.memory_data: Dict[str, Dict[str, Any]] = {}
        self.triggers: List[Callable[[str, str], Any]] = []
        self._lock = threading.RLock()
        self.load_memory()

    def load_memory(self) -> None:
        """加载内存文件，自动转换旧格式"""
        with self._lock:
            if self.memory_file.exists():
                try:
                    with self.memory_file.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                        self.memory_data = self._convert_legacy_format(data)
                    log.info(f"成功加载记忆文件: {self.memory_file}")
                except (json.JSONDecodeError, IOError) as e:
                    log.warning(f"内存文件加载失败，自动初始化空内存: {e}")
                    self.memory_data = {}
            else:
                self.memory_data = {}

    def _convert_legacy_format(self, data: Dict) -> Dict[str, Dict[str, Any]]:
        """将老格式自动转换为新格式（含元数据/标签）"""
        converted = {}
        now = time.time()
        for key, value in data.items():
            if not isinstance(value, dict) or 'value' not in value:
                converted[key] = {
                    'value': value,
                    'created_at': now,
                    'last_accessed': now,
                    'expires_at': None,
                    'tags': [],
                    'hit_count': 0
                }
            else:
                value.setdefault('tags', [])
                value.setdefault('hit_count', 0)
                converted[key] = value
        return converted

    def save_memory(self) -> bool:
        """持久化内存到文件，线程安全"""
        with self._lock:
            try:
                with self.memory_file.open("w", encoding="utf-8") as f:
                    json.dump(self.memory_data, f, ensure_ascii=False, indent=2)
                return True
            except Exception as e:
                log.error(f"保存记忆文件失败: {e}")
                return False

    def _trigger_events(self, action: str, key: str):
        """事件触发支持同步或异步回调"""
        for cb in self.triggers:
            try:
                if asyncio.iscoroutinefunction(cb):
                    asyncio.create_task(cb(action, key))
                else:
                    cb(action, key)
            except Exception as e:
                log.warning(f"触发器执行异常: {e}")

    def register_trigger(self, callback: Callable[[str, str], Any]):
        """注册事件触发器（action=remember/expire/delete等，key为变化项）"""
        self.triggers.append(callback)

    def remember(
        self,
        key: str,
        value: Any,
        expires_after: Optional[float] = None,
        tags: Optional[List[str]] = None
    ) -> None:
        """存储记忆，支持过期和标签"""
        now = time.time()
        expires_at = now + expires_after if expires_after else None
        with self._lock:
            self.memory_data[key] = {
                'value': value,
                'created_at': now,
                'last_accessed': now,
                'expires_at': expires_at,
                'tags': tags or [],
                'hit_count': 0
            }
            self.save_memory()
        self.log_event(f"记忆更新: {key} | 类型: {type(value).__name__} | 过期: {expires_at}")
        self._trigger_events("remember", key)

    def recall(self, key: str, update_access: bool = True) -> Any:
        """读取记忆，自动过期清理，更新访问时间和命中计数"""
        now = time.time()
        with self._lock:
            if key not in self.memory_data:
                return None
            entry = self.memory_data[key]
            if entry.get('expires_at') and now > entry['expires_at']:
                del self.memory_data[key]
                self.save_memory()
                self.log_event(f"记忆过期删除: {key}")
                self._trigger_events("expire", key)
                return None
            if update_access:
                entry['last_accessed'] = now
                entry['hit_count'] += 1
                self.save_memory()
            return entry['value']

    def search(
        self,
        pattern: str,
        use_regex: bool = False,
        search_keys: bool = True,
        search_values: bool = True,
        with_tag: Optional[str] = None
    ) -> List[str]:
        """支持正则、标签等搜索，返回符合key列表"""
        regex = re.compile(pattern) if use_regex else None
        results = []
        with self._lock:
            for key, entry in self.memory_data.items():
                if self._is_expired(entry):
                    continue
                if with_tag and with_tag not in entry.get("tags", []):
                    continue
                if search_keys:
                    if use_regex and regex.search(key):
                        results.append(key)
                    elif pattern in key:
                        results.append(key)
                if search_values and key not in results:
                    if self._search_in_value(entry['value'], pattern, use_regex, regex):
                        results.append(key)
        return results

    def _search_in_value(self, value: Any, pattern: str, use_regex: bool, regex=None) -> bool:
        if isinstance(value, str):
            return bool(regex.search(value)) if use_regex else pattern in value
        elif isinstance(value, dict):
            return any(self._search_in_value(v, pattern, use_regex, regex) for v in value.values())
        elif isinstance(value, list):
            return any(self._search_in_value(item, pattern, use_regex, regex) for item in value)
        return False

    def _is_expired(self, entry: Dict[str, Any]) -> bool:
        if not entry.get('expires_at'):
            return False
        return time.time() > entry['expires_at']

    def clean_expired_memories(self) -> int:
        """清理所有过期记忆并返回数量"""
        now = time.time()
        removed = 0
        with self._lock:
            expired_keys = [k for k, e in self.memory_data.items()
                            if e.get('expires_at') and e['expires_at'] < now]
            for key in expired_keys:
                del self.memory_data[key]
                removed += 1
                self.log_event(f"清理过期记忆: {key}")
                self._trigger_events("expire", key)
            if removed > 0:
                self.save_memory()
        return removed

    def get_metadata(self, key: str) -> Optional[Dict[str, Any]]:
        """获取记忆元数据，包括是否过期"""
        with self._lock:
            if key not in self.memory_data:
                return None
            meta = {k: v for k, v in self.memory_data[key].items() if k != 'value'}
            meta["is_expired"] = self._is_expired(self.memory_data[key])
            return meta

    def tag_memory(self, key: str, tag: str) -> None:
        """给记忆加标签"""
        with self._lock:
            if key in self.memory_data:
                tags = self.memory_data[key].setdefault("tags", [])
                if tag not in tags:
                    tags.append(tag)
                    self.save_memory()

    def delete(self, key: str) -> None:
        """删除指定记忆"""
        with self._lock:
            if key in self.memory_data:
                del self.memory_data[key]
                self.save_memory()
                self.log_event(f"记忆删除: {key}")
                self._trigger_events("delete", key)

    def log_event(self, event: str) -> None:
        """日志事件，追加到日志文件并打印"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        log_line = f"[{timestamp}] {event}"
        try:
            with self.log_file.open("a", encoding="utf-8") as f:
                f.write(log_line + "\n")
        except Exception as e:
            log.error(f"日志写入失败: {e}")
        log.debug(log_line)

# ====== 单例导出及委托方法 ======
memory_engine = MemoryEngine()

def remember(key: str, value: Any, expires_after: Optional[float] = None, tags: Optional[List[str]] = None):
    memory_engine.remember(key, value, expires_after, tags)

def recall(key: str) -> Any:
    return memory_engine.recall(key)

def search(pattern: str, use_regex: bool = False, **kwargs) -> List[str]:
    return memory_engine.search(pattern, use_regex, **kwargs)

def clean_expired_memories() -> int:
    return memory_engine.clean_expired_memories()

def get_metadata(key: str) -> Optional[Dict[str, Any]]:
    return memory_engine.get_metadata(key)

def tag_memory(key: str, tag: str):
    memory_engine.tag_memory(key, tag)

def delete_memory(key: str):
    memory_engine.delete(key)

def log_event(event: str):
    memory_engine.log_event(event)
