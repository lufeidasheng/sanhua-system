# core/aicore/context/context_manager.py

import threading
import time
import json
from typing import List, Dict, Any, Optional, Union, Tuple
from core.core2_0.sanhuatongyu.logger import get_logger

log = get_logger(__name__)

class ContextManagerPlus:
    """
    三花聚顶 · 企业级AI上下文管理器

    - 全局/模块多维上下文
    - 支持上下文长度滚动裁剪
    - 支持“角色+内容”对话链
    - 支持导入/导出/摘要/事件
    - 支持对话轮（user+assistant）抽取
    - 线程安全
    """

    def __init__(
        self,
        global_max_length: int = 20,
        module_max_length: int = 10,
        memory: Optional[Any] = None,
        event_bus: Optional[Any] = None
    ):
        self._global_chain: List[Dict[str, Any]] = []
        self._module_chains: Dict[str, List[Dict[str, Any]]] = {}
        self._lock = threading.RLock()
        self._global_max_length = global_max_length
        self._module_max_length = module_max_length
        self.memory = memory
        self.event_bus = event_bus

    def add_context(self, text: str, role: str = "user", module: Optional[str] = None, meta: Optional[Dict[str, Any]] = None) -> None:
        """
        添加一条上下文记录，role建议"user"、"assistant"、"system"等。
        """
        item = {
            "timestamp": time.time(),
            "role": role,
            "text": text,
            "meta": meta or {}
        }
        with self._lock:
            self._global_chain.append(item)
            if len(self._global_chain) > self._global_max_length:
                self._global_chain.pop(0)
            if module:
                if module not in self._module_chains:
                    self._module_chains[module] = []
                self._module_chains[module].append(item)
                if len(self._module_chains[module]) > self._module_max_length:
                    self._module_chains[module].pop(0)
        # 事件总线通知
        if self.event_bus:
            try:
                if callable(getattr(self.event_bus, "publish", None)):
                    result = self.event_bus.publish("CONTEXT_UPDATED", {"module": module, "item": item})
                    if hasattr(result, "__await__"):
                        import asyncio
                        asyncio.create_task(result)
                else:
                    log.warning("event_bus对象无publish方法")
            except Exception as e:
                log.warning(f"事件发布失败: {e}")

    def get_recent(self, n: int = 5, module: Optional[str] = None, with_role: bool = True) -> List[Union[str, Dict[str, Any]]]:
        """
        获取最近n条上下文。with_role=True返回dict含role和text，False只返回text。
        """
        with self._lock:
            chain = self._module_chains[module][-n:] if module and module in self._module_chains else self._global_chain[-n:]
            if with_role:
                return list(chain)
            return [item["text"] for item in chain]

    def get_all_history(self, module: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取完整上下文历史（全局或指定模块）。"""
        with self._lock:
            if module and module in self._module_chains:
                return list(self._module_chains[module])
            return list(self._global_chain)

    def summarize_history(self, window: int = 20) -> str:
        """
        对最近window条上下文生成“角色+内容”摘要，可用于Prompt构建。
        """
        with self._lock:
            recent = self._global_chain[-window:]
        return "\n".join([f"{item['role']}：{item['text']}" for item in recent])

    def get_last_message(self, role: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        获取最近一条消息（可指定角色）。
        """
        with self._lock:
            if not self._global_chain:
                return None
            if role:
                for item in reversed(self._global_chain):
                    if item["role"] == role:
                        return item
                return None
            return self._global_chain[-1]

    def get_dialog_pairs(self, window: int = 6) -> List[Tuple[str, str]]:
        """
        获取最近window轮（user+assistant）对话。
        """
        with self._lock:
            chain = self._global_chain[-window*2:]  # 最多2*window条
        pairs, user, assistant = [], None, None
        for item in chain:
            if item["role"] == "user":
                user = item["text"]
            elif item["role"] == "assistant" and user is not None:
                assistant = item["text"]
                pairs.append((user, assistant))
                user = None
        return pairs[-window:]

    def finalize_response(self, query: str, response: str, module: Optional[str] = None) -> str:
        """
        标准化记录一次“用户+助手”对话。
        """
        self.add_context(query, role="user", module=module)
        self.add_context(response, role="assistant", module=module)
        try:
            if self.memory:
                self.memory.log_event(f"用户提问: {query}")
                self.memory.log_event(f"助手回答: {response}")
        except Exception as e:
            log.warning(f"日志记录失败: {e}")
        return response

    def clear(self, module: Optional[str] = None) -> None:
        """
        清空上下文。
        """
        with self._lock:
            if module and module in self._module_chains:
                self._module_chains[module] = []
            elif module is None:
                self._global_chain.clear()
                self._module_chains.clear()

    def export_history(self, path: str, module: Optional[str] = None) -> None:
        """
        导出上下文历史到文件。
        """
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.get_all_history(module), f, ensure_ascii=False, indent=2)
        log.info(f"已导出上下文历史到 {path}")

    def import_history(self, path: str, module: Optional[str] = None) -> None:
        """
        导入上下文历史。
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        with self._lock:
            if module:
                self._module_chains[module] = data
            else:
                self._global_chain = data
        log.info(f"已导入上下文历史 {path}")

if __name__ == "__main__":
    cm = ContextManagerPlus()
    cm.add_context("你好，今天状态如何？", role="user")
    cm.add_context("很棒，准备继续开发AICore！", role="assistant")
    print("最近上下文：", cm.get_recent(2, with_role=True))
    print("全局摘要：\n", cm.summarize_history())
    print("最近一轮：", cm.get_dialog_pairs(1))
