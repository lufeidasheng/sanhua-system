# ==========================================================
# 🌸 三花聚顶 · ModelEngine 3.1
# 企业级模型引擎模块（增强版）
# ==========================================================

import threading
import requests
import logging
import json
import time
import concurrent.futures
from typing import List, Optional, Dict, Any, Callable
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, Future
from pathlib import Path
from contextlib import contextmanager

logger = logging.getLogger("ModelEngine")

# ==========================================================
# 🌐 ModelEndpoint —— 模型端点结构
# ==========================================================
class ModelEndpoint:
    def __init__(self, url: str, backend: str, models: Optional[List[str]] = None,
                 latency: float = 0.0, health: bool = True):
        self.url = url.rstrip("/")
        self.backend = backend
        self.models = models or []
        self.latency = latency
        self.health = health

    def __repr__(self):
        return f"ModelEndpoint({self.backend}@{self.url}, models={len(self.models)}, latency={self.latency:.2f}s)"


# ==========================================================
# 🔍 ModelScanner —— 自动发现与缓存
# ==========================================================
class ModelScanner:
    COMMON_PORTS = [8080, 11434, 8000, 5000, 7860, 8081]
    SCAN_TIMEOUT = 2.5

    def __init__(self, host="127.0.0.1", timeout=SCAN_TIMEOUT):
        self.host = host
        self.timeout = timeout
        self.cache_file = Path(".model_endpoints_cache.json")
        self.cache_ttl = 300

    def _probe_llama(self, url: str):
        try:
            t0 = time.time()
            res = requests.post(f"{url}/completion", 
                               json={"prompt": "", "n_predict": 1}, 
                               timeout=self.timeout)
            latency = time.time() - t0
            if res.status_code in (200, 400, 422):
                return ModelEndpoint(url, "llama", latency=latency)
        except Exception:
            pass
        return None

    def _probe_ollama(self, url: str):
        try:
            t0 = time.time()
            res = requests.get(f"{url}/api/tags", timeout=self.timeout)
            latency = time.time() - t0
            if res.status_code == 200:
                models = [m["name"] for m in res.json().get("models", []) if m.get("name")]
                return ModelEndpoint(url, "ollama", models, latency)
        except Exception:
            pass
        return None

    def _probe_openai(self, url: str):
        try:
            t0 = time.time()
            res = requests.get(f"{url}/v1/models", timeout=self.timeout)
            latency = time.time() - t0
            if res.status_code == 200:
                models = [m["id"] for m in res.json().get("data", []) if m.get("id")]
                return ModelEndpoint(url, "openai", models, latency)
        except Exception:
            pass
        return None

    def _probe_port(self, port: int):
        base = f"http://{self.host}:{port}"
        for probe in (self._probe_llama, self._probe_ollama, self._probe_openai):
            ep = probe(base)
            if ep:
                return ep
        return None

    def _load_cache(self):
        if not self.cache_file.exists(): 
            return []
        try:
            data = json.loads(self.cache_file.read_text())
            if time.time() - data.get("timestamp", 0) > self.cache_ttl:
                return []
            return [ModelEndpoint(**e) for e in data.get("endpoints", [])]
        except Exception:
            return []

    def _save_cache(self, endpoints: List[ModelEndpoint]):
        try:
            payload = {
                "timestamp": time.time(),
                "endpoints": [e.__dict__ for e in endpoints]
            }
            self.cache_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        except Exception:
            pass

    def scan(self, use_cache=True) -> List[ModelEndpoint]:
        if use_cache:
            cache = self._load_cache()
            if cache:
                return cache

        found = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(self._probe_port, p): p for p in self.COMMON_PORTS}
            for f in concurrent.futures.as_completed(futures):
                ep = f.result()
                if ep:
                    logger.info(f"🔍 发现服务: {ep}")
                    found.append(ep)
        found.sort(key=lambda x: x.latency)
        if found:
            self._save_cache(found)
        return found


# ==========================================================
# ⚙️ ModelConfig —— 模型配置结构
# ==========================================================
@dataclass
class ModelConfig:
    name: str
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 2048
    top_k: int = 40
    repeat_penalty: float = 1.1
    stop: List[str] = None

    def __post_init__(self):
        if self.stop is None:
            self.stop = ["<|endoftext|>", "<|eot_id|>"]

    def validate(self):
        errs = []
        if not self.name: 
            errs.append("模型名称不能为空")
        if not (0 <= self.temperature <= 2): 
            errs.append("temperature 必须在0~2之间")
        if not (0 <= self.top_p <= 1): 
            errs.append("top_p 必须在0~1之间")
        if not (1 <= self.max_tokens <= 128000): 
            errs.append("max_tokens 必须在1~128000之间")
        if self.top_k < 1:
            errs.append("top_k 必须大于0")
        if self.repeat_penalty < 1.0:
            errs.append("repeat_penalty 必须大于等于1.0")
        if not isinstance(self.stop, list):
            errs.append("stop 必须是列表")
        return errs

    def to_dict(self):
        return asdict(self)


# ==========================================================
# 🤖 ModelRouter —— 模型路由与调度策略
# ==========================================================
class ModelRouter:
    def __init__(self, endpoints: List[ModelEndpoint]):
        self.endpoints = endpoints

    def best(self, backend_preference="auto") -> Optional[ModelEndpoint]:
        if not self.endpoints:
            return None
        if backend_preference != "auto":
            eps = [e for e in self.endpoints if e.backend == backend_preference]
            return eps[0] if eps else self.endpoints[0]
        return sorted(self.endpoints, key=lambda e: e.latency)[0]


# ==========================================================
# 🧠 ModelEngine —— 三花聚顶核心模型引擎
# ==========================================================
class ModelEngine:
    def __init__(self,
                 model_name="qwen3-latest",
                 api_url="",
                 backend="auto",
                 config_file="model_engine_config.json",
                 timeout=60,
                 max_retries=3,
                 session_pool_size=8,
                 max_workers=4):
        self._config = ModelConfig(name=model_name)
        self.api_url = api_url.rstrip("/") if api_url else ""
        self.backend = backend
        self.timeout = timeout
        self.max_retries = max_retries
        self.config_file = config_file

        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.session = self._init_session(session_pool_size)
        self.scanner = ModelScanner()
        self.stats = {"total": 0, "fail": 0, "avg_latency": 0.0}
        self.router = None

        self._initialize()

    def _init_session(self, pool_size):
        s = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=pool_size,
                                                pool_maxsize=pool_size, max_retries=2)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        s.headers.update({
            "User-Agent": "Sanhua/ModelEngine3.1", 
            "Content-Type": "application/json"
        })
        return s

    # -------------------- 初始化 --------------------
    def _initialize(self):
        if not self._load_config():
            eps = self.scanner.scan()
            self.router = ModelRouter(eps)
            best = self.router.best(self.backend)
            if best:
                self.api_url, self.backend = best.url, best.backend
                logger.info(f"✅ 自动绑定模型端点: {self.backend}@{self.api_url}")
        self._save_config()
        self._warmup()

    def _load_config(self):
        try:
            p = Path(self.config_file)
            if not p.exists(): 
                return False
            data = json.loads(p.read_text())
            self.api_url = data.get("api_url", self.api_url)
            self.backend = data.get("backend", self.backend)
            if mc := data.get("model_config"):
                self._config = ModelConfig(**mc)
            logger.info(f"📂 加载配置成功: {self.config_file}")
            return True
        except Exception:
            return False

    def _save_config(self):
        try:
            config_path = Path(self.config_file)
            config_path.parent.mkdir(parents=True, exist_ok=True)
            
            config_path.write_text(json.dumps({
                "api_url": self.api_url,
                "backend": self.backend,
                "model_config": self._config.to_dict(),
                "timestamp": time.time(),
                "version": "3.1"
            }, indent=2, ensure_ascii=False))
            logger.debug(f"配置已保存: {self.config_file}")
        except Exception as e:
            logger.warning(f"保存配置失败: {e}")

    def _warmup(self):
        try:
            logger.info("🔥 模型引擎预热中...")
            self.call_model("你好", timeout=5, retries=1)
        except Exception:
            logger.warning("预热失败，可忽略。")

    # -------------------- 健康检查 --------------------
    def health_check(self, timeout: int = 5) -> bool:
        """检查当前端点是否健康"""
        if not self.api_url:
            return False
            
        try:
            if self.backend == "ollama":
                resp = self.session.get(f"{self.api_url}/api/version", timeout=timeout)
            elif self.backend == "llama":
                resp = self.session.post(
                    f"{self.api_url}/completion", 
                    json={"prompt": "test", "n_predict": 1},
                    timeout=timeout
                )
            else:
                resp = self.session.get(f"{self.api_url}/health", timeout=timeout)
                
            return resp.status_code == 200
        except Exception:
            return False

    # -------------------- 模型切换 --------------------
    def switch_model(self, model_name: str):
        if not model_name:
            return False
            
        # 验证配置
        temp_config = self._config.to_dict()
        temp_config["name"] = model_name
        errors = ModelConfig(**temp_config).validate()
        if errors:
            logger.error(f"模型配置验证失败: {errors}")
            return False
            
        self._config.name = model_name
        self._save_config()
        logger.info(f"🔄 已切换模型: {model_name}")
        return True

    # -------------------- 模型调用 --------------------
    def call_model(self, prompt: str, stream=False, timeout=None, retries=None,
                   stream_callback: Optional[Callable] = None) -> str:
        timeout = timeout or self.timeout
        retries = retries or self.max_retries
        self.stats["total"] += 1
        t0 = time.time()

        for attempt in range(1, retries + 1):
            try:
                # 健康检查（仅在第一次尝试）
                if attempt == 1 and not self.health_check():
                    logger.warning("端点健康检查失败，尝试继续...")

                payload = self._build_payload(prompt, stream)
                url = self._get_url()
                with self.lock:
                    r = self.session.post(url, json=payload, timeout=timeout, stream=stream)
                
                if stream:
                    result = self._handle_stream(r, stream_callback)
                else:
                    result = self._handle_json(r)
                    
                self._update_latency(time.time() - t0)
                return result
                
            except requests.exceptions.Timeout:
                logger.warning(f"请求超时 (第{attempt}/{retries}次)")
                if attempt == retries:
                    self.stats["fail"] += 1
                    return "❗ 请求超时，请检查网络或服务状态"
                    
            except requests.exceptions.ConnectionError:
                logger.warning(f"连接错误 (第{attempt}/{retries}次)")
                if attempt == retries:
                    self.stats["fail"] += 1
                    return "❗ 无法连接到模型服务"
                    
            except requests.exceptions.HTTPError as e:
                logger.warning(f"HTTP错误 {e.response.status_code} (第{attempt}/{retries}次)")
                if attempt == retries:
                    self.stats["fail"] += 1
                    return f"❗ 服务返回错误: {e.response.status_code}"
                    
            except Exception as e:
                logger.warning(f"未知错误 (第{attempt}/{retries}次): {e}")
                if attempt == retries:
                    self.stats["fail"] += 1
                    return "❌ 模型调用失败"

            time.sleep(min(2 ** attempt, 8))
    
        return "❌ 所有重试均失败"

    def _get_url(self):
        if self.backend == "ollama": 
            return f"{self.api_url}/api/generate"
        if self.backend == "llama": 
            return f"{self.api_url}/completion"
        return f"{self.api_url}/v1/completions"

    def _build_payload(self, prompt, stream):
        cfg = self._config
        if self.backend == "ollama":
            return {
                "model": cfg.name, 
                "prompt": prompt, 
                "stream": stream,
                "options": {
                    "temperature": cfg.temperature, 
                    "top_p": cfg.top_p,
                    "top_k": cfg.top_k, 
                    "num_ctx": cfg.max_tokens,
                    "repeat_penalty": cfg.repeat_penalty, 
                    "stop": cfg.stop
                }
            }
        return {
            "prompt": prompt, 
            "temperature": cfg.temperature, 
            "top_p": cfg.top_p,
            "max_tokens": cfg.max_tokens, 
            "stream": stream, 
            "stop": cfg.stop
        }

    def _handle_json(self, resp):
        resp.raise_for_status()
        data = resp.json()
        for k in ("response", "message", "content", "completion", "text"):
            if v := data.get(k):
                return str(v).strip()
        return json.dumps(data, ensure_ascii=False)

    def _handle_stream(self, resp, cb):
        resp.raise_for_status()
        text = ""
        for line in resp.iter_lines():
            if not line: 
                continue
            try:
                data = json.loads(line)
                
                # 多后端流式格式兼容
                if self.backend == "ollama":
                    if data.get("done", False):
                        break
                    chunk = data.get("response", "")
                elif self.backend == "llama":
                    chunk = data.get("content", "")
                else:  # openai
                    choices = data.get("choices", [{}])
                    chunk = choices[0].get("text", "") if choices else ""
                
                if chunk:
                    text += chunk
                    if cb:
                        cb(chunk)
                        
            except json.JSONDecodeError:
                continue
        return text

    # -------------------- 统计与管理 --------------------
    def _update_latency(self, latency):
        n = self.stats["total"] - self.stats["fail"]
        old = self.stats["avg_latency"]
        self.stats["avg_latency"] = (old * (n - 1) + latency) / max(n, 1)

    def get_stats(self):
        return self.stats.copy()

    def release(self):
        self.session.close()
        self.executor.shutdown(wait=True)
        logger.info("✅ 模型引擎已释放")

    def __enter__(self): 
        return self
        
    def __exit__(self, *_): 
        self.release()


# ==========================================================
# 🌸 使用示例
# ==========================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    with ModelEngine() as engine:
        print(f"后端: {engine.backend}  @  {engine.api_url}")
        print(f"模型: {engine._config.name}")
        print(f"健康状态: {'✅' if engine.health_check() else '❌'}")
        
        # 同步调用
        result = engine.call_model('用一句话介绍"三花聚顶"项目')
        print(f"同步输出: {result}")

        # 流式调用
        print("流式输出: ", end="")
        engine.call_model("写一首关于AI的短诗", 
                         stream=True, 
                         stream_callback=lambda c: print(c, end="", flush=True))
        print()
        
        print("统计:", engine.get_stats())