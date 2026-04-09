"""
三花聚顶 · code_reader 功能模块（增强全局标准化版）
"""
import os
import ast
import logging
import hashlib
import stat
import threading
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from abc import ABC, abstractmethod

from core.core2_0.sanhuatongyu.module.base import BaseModule

# ==== 日志配置 ====
logger = logging.getLogger("code_reader")
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# ==== 数据结构定义 ====
@dataclass
class FileMetadata:
    path: str
    size: int
    created: float
    modified: float
    permissions: str
    owner: str
    group: str
    file_type: str
    encoding: str
    md5_hash: str
    sha256_hash: str
    inode: int
    device: int
    selinux_context: str = ""

@dataclass
class CodeAnalysisResult:
    structure: Dict[str, Any]
    quality: Dict[str, Any]
    security: List[Dict[str, Any]]
    performance: List[Dict[str, Any]]

# ==== 核心分析器架构 ====
class CodeAnalyzer(ABC):
    @classmethod
    @abstractmethod
    def supported_extensions(cls) -> List[str]:
        pass
    @abstractmethod
    def analyze(self, source: str, filepath: str = "") -> CodeAnalysisResult:
        pass

class PythonAnalyzer(CodeAnalyzer):
    @classmethod
    def supported_extensions(cls): return ['.py', '.pyw']
    def analyze(self, source: str, filepath: str = "") -> CodeAnalysisResult:
        structure = self._extract_structure(source)
        return CodeAnalysisResult(
            structure=structure,
            quality={"complexity": len(structure.get("functions", [])), "style_issues": []},
            security=[],
            performance=[]
        )
    def _extract_structure(self, source: str) -> Dict[str, Any]:
        structure = {"functions": [], "classes": [], "imports": [], "global_variables": [], "metadata": {}}
        try:
            tree = ast.parse(source)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    structure["functions"].append({"name": node.name, "args": [a.arg for a in node.args.args], "doc": ast.get_docstring(node)})
                elif isinstance(node, ast.ClassDef):
                    structure["classes"].append({"name": node.name, "doc": ast.get_docstring(node)})
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    try: structure["imports"].append(ast.unparse(node))
                    except: pass
        except Exception as e:
            structure["metadata"]["error"] = str(e)
        return structure

class JavaScriptAnalyzer(CodeAnalyzer):
    @classmethod
    def supported_extensions(cls): return ['.js', '.jsx', '.ts', '.tsx']
    def analyze(self, source: str, filepath: str = "") -> CodeAnalysisResult:
        return CodeAnalysisResult(
            structure={"file_type": "javascript", "metadata": {"analysis_level": "basic"}},
            quality={}, security=[], performance=[]
        )

class AnalyzerManager:
    def __init__(self):
        self._analyzers = {}
        self.register(PythonAnalyzer())
        self.register(JavaScriptAnalyzer())
    def register(self, analyzer: CodeAnalyzer):
        for ext in analyzer.supported_extensions():
            self._analyzers[ext] = analyzer
    def analyze(self, source: str, filepath: str = "") -> CodeAnalysisResult:
        ext = os.path.splitext(filepath)[1].lower() if filepath else ""
        analyzer = self._analyzers.get(ext)
        if analyzer: return analyzer.analyze(source, filepath)
        return CodeAnalysisResult(structure={"file_type": ext}, quality={}, security=[], performance=[])

class AnalysisCache:
    def __init__(self, max_size=500):
        self._cache = {}
        self._max_size = max_size
        self._lock = threading.Lock()
    def get(self, key: str):
        with self._lock:
            return self._cache.get(key)

    def set(self, key: str, value):
        with self._lock:
            if len(self._cache) >= self._max_size:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = value
    def generate_key(self, source, filepath): return f"{hashlib.sha256(source.encode()).hexdigest()}:{filepath}"

class ParallelAnalyzer:
    def __init__(self, analyzer_manager: AnalyzerManager, max_workers=4):
        self.analyzer_manager = analyzer_manager
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
    def analyze_files(self, filepaths: List[str]):
        results, futures = {}, {}
        for filepath in filepaths:
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f: content = f.read()
                fut = self.executor.submit(self.analyzer_manager.analyze, content, filepath)
                futures[fut] = filepath
            except Exception as e:
                results[filepath] = CodeAnalysisResult(structure={"error": str(e)}, quality={}, security=[], performance=[])
        for fut in as_completed(futures):
            fp = futures[fut]
            try: results[fp] = fut.result()
            except Exception as e:
                results[fp] = CodeAnalysisResult(structure={"error": str(e)}, quality={}, security=[], performance=[])
        return results
    def shutdown(self): self.executor.shutdown(wait=True)

class CodeReaderModule(BaseModule):
    def __init__(self, meta=None, context=None):
        super().__init__(meta, context)
        self.analyzer_manager = AnalyzerManager()
        self.cache = AnalysisCache()
        self.parallel_analyzer = ParallelAnalyzer(self.analyzer_manager)
        logger.info("CodeReaderModule 初始化完成")

    def preload(self): logger.info(f"{getattr(self.meta,'name','code_reader')} 预加载完成")
    def setup(self):
        logger.info(f"{getattr(self.meta,'name','code_reader')} 设置完成，注册标准动作")
        dispatcher = getattr(self.context, "action_dispatcher", None)
        if dispatcher and not getattr(self, "_registered", False):
            register_actions(dispatcher, self)
            self._registered = True
    def start(self): logger.info(f"{getattr(self.meta,'name','code_reader')} 模块启动")
    def stop(self): 
        logger.info(f"{getattr(self.meta,'name','code_reader')} 模块停止")
        self.parallel_analyzer.shutdown()
    def handle_event(self, event_type: str, data: dict): pass

    def read_file(self, params: dict, **kwargs):
        filepath = params.get("filepath"); max_size = params.get("max_size", 5*1024*1024)
        if not filepath or not os.path.isfile(filepath): return {"error": "文件不存在"}
        try:
            if not self._is_safe_path(filepath): return {"error": "访问路径不安全"}
            meta = self._get_file_metadata(filepath)
            if meta.size > max_size: return {"error": f"文件大小超过限制({max_size}字节)"}
            with open(filepath, "r", encoding=meta.encoding, errors="ignore") as f: content = f.read()
            return {"metadata": vars(meta), "content": content}
        except Exception as e: logger.error(f"读取文件失败: {e}"); return {"error": str(e)}

    def analyze_code(self, params: dict, **kwargs):
        source = params.get("source", ""); filepath = params.get("filepath", "")
        cache_key = self.cache.generate_key(source, filepath)
        cached = self.cache.get(cache_key)
        if cached: return self._format_result(cached)
        result = self.analyzer_manager.analyze(source, filepath)
        self.cache.set(cache_key, result)
        return self._format_result(result)

    def batch_analyze(self, params: dict, **kwargs):
        filepaths = params.get("filepaths", [])
        if not filepaths: return {"error": "未提供文件路径列表"}
        results = self.parallel_analyzer.analyze_files(filepaths)
        return {"results": {fp: self._format_result(res) for fp, res in results.items()}}

    def _get_file_metadata(self, filepath: str) -> FileMetadata:
        stat_info = os.stat(filepath)
        try: import pwd, grp; owner = pwd.getpwuid(stat_info.st_uid).pw_name; group = grp.getgrgid(stat_info.st_gid).gr_name
        except Exception: owner = str(stat_info.st_uid); group = str(stat_info.st_gid)
        with open(filepath, "rb") as f: content = f.read()
        return FileMetadata(
            path=filepath, size=stat_info.st_size, created=stat_info.st_ctime, modified=stat_info.st_mtime,
            permissions=stat.filemode(stat_info.st_mode), owner=owner, group=group,
            file_type=os.path.splitext(filepath)[1].lower(),
            encoding=self._detect_encoding(content),
            md5_hash=hashlib.md5(content).hexdigest(), sha256_hash=hashlib.sha256(content).hexdigest(),
            inode=stat_info.st_ino, device=stat_info.st_dev, selinux_context=self._get_selinux_context(filepath)
        )
    def _detect_encoding(self, content: bytes) -> str:
        try: import chardet; d = chardet.detect(content); return d["encoding"] if d else "utf-8"
        except ImportError: return "utf-8"
    def _is_safe_path(self, filepath: str) -> bool:
        allowed = [os.path.abspath("./"), os.path.expanduser("~/projects")]
        real = os.path.realpath(filepath); return any(real.startswith(path) for path in allowed)
    def _get_selinux_context(self, filepath: str) -> str:
        try: import ctypes; buf = ctypes.create_string_buffer(256); libc = ctypes.CDLL("libc.so.6"); ret = libc.getfilecon(filepath.encode(), ctypes.byref(buf))
        except Exception: return ""
        return buf.value.decode() if ret == 0 else ""
    def _format_result(self, result: CodeAnalysisResult) -> Dict[str, Any]:
        return {
            "structure": result.structure,
            "quality": result.quality,
            "security_issues": result.security,
            "performance_issues": result.performance
        }

def register_actions(dispatcher, mod_or_context=None):
    # 兼容 context/context-less
    mod = mod_or_context if isinstance(mod_or_context, CodeReaderModule) else None
    if mod is None and hasattr(dispatcher, "get_module_meta"):
        mod = CodeReaderModule(meta=dispatcher.get_module_meta("code_reader"), context=getattr(dispatcher, "context", None))
    # 注册
    dispatcher.register_action(
        "code_reader.read_file", mod.read_file,
        description="读取文件内容", parameters={
            "filepath": {"type": "string", "required": True},
            "max_size": {"type": "integer", "default": 5242880}
        }
    )
    dispatcher.register_action(
        "code_reader.analyze_code", mod.analyze_code,
        description="分析代码结构和质量", parameters={
            "source": {"type": "string", "required": False},
            "filepath": {"type": "string", "required": False}
        }
    )
    dispatcher.register_action(
        "code_reader.batch_analyze", mod.batch_analyze,
        description="批量分析多个文件", parameters={
            "filepaths": {"type": "list", "required": True}
        }
    )
    logger.info("code_reader 动作注册完成")

MODULE_CLASS = CodeReaderModule
