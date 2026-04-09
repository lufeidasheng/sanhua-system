# core/aicore/model_engine.py
import threading
import requests
import logging
from typing import List, Optional, Dict, Any, Union
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, Future
from functools import lru_cache
import json

logger = logging.getLogger("ModelEngine")
logger.setLevel(logging.DEBUG)  # 保持DEBUG级别

@dataclass
class ModelConfig:
    """模型配置数据结构"""
    name: str
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 2048

class ModelEngine:
    """
    三花聚顶 · 增强版模型引擎
    功能增强:
    - 连接池管理
    - 自动重试机制
    - 模型配置管理
    - 异步调用支持
    - 更完善的错误处理
    """

    DEFAULT_TIMEOUT = 60
    MAX_RETRIES = 3
    CONNECTION_POOL_SIZE = 5

    def __init__(
        self,
        model_name: str = "llama3:latest",
        api_url: str = "http://localhost:11434/api/generate",
        session_pool_size: int = CONNECTION_POOL_SIZE
    ):
        self._model_config = ModelConfig(name=model_name)
        self.api_url = api_url
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=3)
        
        # 配置连接池
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=session_pool_size,
            pool_maxsize=session_pool_size
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

    def build_full_prompt(
        self,
        query: str,
        context_manager: Optional[Any] = None,
        memory: Optional[Union[Dict, str]] = None,
        system_prompt: str = "",
        max_context_length: int = 5
    ) -> str:
        """
        构建完整Prompt，增强功能:
        - 支持多种memory格式
        - 可配置上下文长度
        - 更完善的日志
        """
        recent_context: List[str] = []
        if context_manager and hasattr(context_manager, "get_recent"):
            recent_context = context_manager.get_recent(max_context_length)
        
        # 处理memory格式
        memory_str = ""
        if memory:
            if isinstance(memory, dict):
                try:
                    memory_str = json.dumps(memory, ensure_ascii=False)
                except (TypeError, ValueError):
                    memory_str = str(memory)
            else:
                memory_str = str(memory)

        prompt_parts = [
            system_prompt.strip(),
            "\n\n记忆信息:\n" + memory_str if memory_str else "",
            "\n\n最近对话:\n" + "\n".join(recent_context) if recent_context else "",
            f"\n\n用户：{query}\n助手："
        ]
        final_prompt = "".join(filter(None, prompt_parts))
        
        logger.debug(f"构建Prompt完成，长度: {len(final_prompt)}")
        logger.debug(f"Prompt预览:\n{final_prompt[:200]}...")
        return final_prompt

    def call_model(
        self,
        prompt: str,
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = MAX_RETRIES
    ) -> str:
        """
        增强版模型调用:
        - 自动重试机制
        - 更详细的错误处理
        - 连接池管理
        """
        for attempt in range(1, retries + 1):
            try:
                logger.debug(f"尝试第{attempt}次调用 (模型: {self._model_config.name})")
                
                request_data = {
                    "model": self._model_config.name,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": self._model_config.temperature,
                        "top_p": self._model_config.top_p,
                        "num_ctx": self._model_config.max_tokens
                    }
                }
                
                with self.lock:
                    response = self.session.post(
                        self.api_url,
                        json=request_data,
                        timeout=timeout
                    )
                
                logger.debug(f"响应状态: {response.status_code}")
                response.raise_for_status()
                
                data = response.json()
                reply = data.get("response") or data.get("message") or "（无返回内容）"
                
                logger.debug(f"成功获取回复，长度: {len(reply)}")
                return reply

            except requests.exceptions.Timeout:
                if attempt == retries:
                    logger.error(f"模型调用超时 (已重试{retries}次)")
                    return "❗ 模型响应超时，请稍后再试"
                logger.warning(f"请求超时，准备重试 ({attempt}/{retries})")
                
            except requests.exceptions.RequestException as e:
                logger.error(f"请求异常: {str(e)}")
                return f"❌ 请求失败: {str(e)}"
                
            except Exception as e:
                logger.error(f"未知错误: {str(e)}", exc_info=True)
                return f"❌ 发生错误: {str(e)}"

    def call_model_async(self, prompt: str) -> Future:
        """异步调用接口"""
        return self.executor.submit(self.call_model, prompt)

    def switch_model(self, model_name: str) -> bool:
        """切换模型并验证可用性"""
        try:
            with self.lock:
                # 先验证模型是否存在
                response = self.session.post(
                    f"{self.api_url.rsplit('/', 1)[0]}/show",
                    json={"name": model_name},
                    timeout=10
                )
                if response.status_code != 200:
                    logger.error(f"模型{model_name}验证失败")
                    return False
                
                self._model_config.name = model_name
                logger.info(f"成功切换模型至 {model_name}")
                return True
        except Exception as e:
            logger.error(f"模型切换失败: {str(e)}")
            return False

    @property
    def current_model(self) -> str:
        """获取当前模型名称"""
        return self._model_config.name

    def get_available_models(self) -> List[str]:
        """获取可用模型列表"""
        try:
            response = self.session.get(f"{self.api_url.rsplit('/', 1)[0]}/tags")
            return [m['name'] for m in response.json().get('models', [])]
        except Exception as e:
            logger.warning(f"获取模型列表失败，使用默认列表: {str(e)}")
            return ["llama2", "llama3", "phi3", "qwen", "yi"]

    def update_model_config(
        self,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> None:
        """更新模型参数"""
        with self.lock:
            if temperature is not None:
                self._model_config.temperature = temperature
            if top_p is not None:
                self._model_config.top_p = top_p
            if max_tokens is not None:
                self._model_config.max_tokens = max_tokens
        logger.info(f"更新模型配置: {self._model_config}")

    def release_resources(self):
        """释放所有资源"""
        self.session.close()
        self.executor.shutdown(wait=False)
        logger.info("模型引擎资源已释放")


if __name__ == "__main__":
    # 增强的测试用例
    import time
    
    # 初始化引擎
    engine = ModelEngine()
    print(f"当前模型: {engine.current_model}")
    print(f"可用模型: {engine.get_available_models()}")
    
    # 测试Prompt构建
    prompt = engine.build_full_prompt(
        query="三花聚顶项目有什么特点？",
        system_prompt="你是一个知识渊博的AI助手",
        memory={"user": "开发者", "project": "三花聚顶"}
    )
    print("\n==== 生成Prompt ====")
    print(prompt[:500] + "..." if len(prompt) > 500 else prompt)
    
    # 测试同步调用
    print("\n==== 同步调用测试 ====")
    start_time = time.time()
    result = engine.call_model(prompt)
    print(f"耗时: {time.time() - start_time:.2f}s")
    print("响应结果:", result[:200] + "..." if len(result) > 200 else result)
    
    # 测试异步调用
    print("\n==== 异步调用测试 ====")
    future = engine.call_model_async(prompt)
    while not future.done():
        print("等待响应...")
        time.sleep(0.3)
    print("异步结果:", future.result()[:200] + "...")
    
    # 测试模型切换
    print("\n==== 模型切换测试 ====")
    if engine.switch_model("llama2"):
        print(f"已切换到: {engine.current_model}")
    else:
        print("切换失败")
    
    # 资源释放
    engine.release_resources()
