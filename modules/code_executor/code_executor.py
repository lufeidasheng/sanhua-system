import traceback
import sys
import io
import ast
import contextlib
import time
import logging
import multiprocessing
import resource
import os
import tempfile
import shutil
from typing import Any, Dict, List, Tuple, Callable, Optional
import importlib.util

# 模块元信息
__version__ = "3.1.0"
__description__ = "Fedora优化的安全代码执行引擎，支持沙箱隔离、资源限制、SELinux集成，安全执行Python代码块与函数。"

# 日志配置
logger = logging.getLogger("code_executor")
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Fedora特定安全模块检测
try:
    import selinux
    SELINUX_ENABLED = True
except ImportError:
    SELINUX_ENABLED = False
    logger.info("SELinux 未安装或未启用")

# 资源限制
FEDORA_RESOURCE_LIMITS = {
    'RLIMIT_CPU': 10,  # 秒
    'RLIMIT_AS': 256 * 1024 * 1024,  # 内存256MB
    'RLIMIT_FSIZE': 50 * 1024 * 1024,  # 文件大小50MB
    'RLIMIT_NPROC': 50,  # 进程数限制
    'RLIMIT_NOFILE': 50  # 文件描述符
}

class SecurityViolationException(Exception):
    pass

class ResourceLimitException(Exception):
    pass

class CodeExecutor:
    def __init__(self, timeout: int = 10, max_output_length: int = 10000):
        self.timeout = timeout
        self.max_output_length = max_output_length
        self.safe_modules = ['math', 'json', 'datetime', 'collections', 're', 'random', 'itertools']
        self.restricted_modules = ['os', 'sys', 'subprocess', 'shutil', 'socket', 'multiprocessing']
        self.execution_count = 0
        logger.info("代码执行器初始化完成 (Fedora兼容版)")

    def _create_safe_environment(self) -> dict:
        env = {
            '__builtins__': {
                'print': print,
                'len': len,
                'range': range,
                'list': list,
                'dict': dict,
                'set': set,
                'str': str,
                'int': int,
                'float': float,
                'bool': bool,
                'type': type,
                'isinstance': isinstance,
                'enumerate': enumerate,
                'zip': zip,
                'min': min,
                'max': max,
                'sum': sum,
                'sorted': sorted,
                'reversed': reversed,
                'filter': filter,
                'map': map,
                'any': any,
                'all': all,
                'abs': abs,
                'round': round,
            }
        }
        for mod_name in self.safe_modules:
            try:
                env[mod_name] = importlib.import_module(mod_name)
            except ImportError:
                logger.warning(f"无法导入安全模块: {mod_name}")
        if SELINUX_ENABLED:
            env['__security_context__'] = selinux.getcon()[1]
        return env

    def _validate_code(self, code_str: str) -> bool:
        try:
            tree = ast.parse(code_str)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        if alias.name in self.restricted_modules:
                            logger.warning(f"禁止导入受限模块: {alias.name}")
                            return False
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    logger.warning("禁止在代码中定义函数或类")
                    return False
                if isinstance(node, ast.Call):
                    if (isinstance(node.func, ast.Attribute) and
                        isinstance(node.func.value, ast.Name) and
                        node.func.value.id == 'os' and
                        node.func.attr in ['system', 'popen', 'remove', 'rmdir']):
                        logger.warning(f"禁止调用危险OS方法: {node.func.attr}")
                        return False
                    if (isinstance(node.func, ast.Name) and
                        node.func.id in ['exec', 'eval', 'system']):
                        logger.warning(f"禁止执行命令: {node.func.id}")
                        return False
            return True
        except Exception as e:
            logger.error(f"代码验证失败: {e}")
            return False

    def _set_resource_limits(self):
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (FEDORA_RESOURCE_LIMITS['RLIMIT_CPU'], FEDORA_RESOURCE_LIMITS['RLIMIT_CPU']))
            resource.setrlimit(resource.RLIMIT_AS, (FEDORA_RESOURCE_LIMITS['RLIMIT_AS'], FEDORA_RESOURCE_LIMITS['RLIMIT_AS']))
            resource.setrlimit(resource.RLIMIT_FSIZE, (FEDORA_RESOURCE_LIMITS['RLIMIT_FSIZE'], FEDORA_RESOURCE_LIMITS['RLIMIT_FSIZE']))
            resource.setrlimit(resource.RLIMIT_NPROC, (FEDORA_RESOURCE_LIMITS['RLIMIT_NPROC'], FEDORA_RESOURCE_LIMITS['RLIMIT_NPROC']))
            resource.setrlimit(resource.RLIMIT_NOFILE, (FEDORA_RESOURCE_LIMITS['RLIMIT_NOFILE'], FEDORA_RESOURCE_LIMITS['RLIMIT_NOFILE']))
        except Exception as e:
            logger.error(f"设置资源限制失败: {e}")

    def _truncate_output(self, output: str) -> str:
        if len(output) > self.max_output_length:
            trunc_msg = f"\n\n[输出被截断，超过{self.max_output_length}字符限制]"
            return output[:self.max_output_length - len(trunc_msg)] + trunc_msg
        return output

    def _run_in_sandbox(self, func, *args, **kwargs):
        ctx = multiprocessing.get_context('spawn')
        result_queue = ctx.Queue()
        def worker(queue, *args, **kwargs):
            temp_dir = None
            try:
                temp_dir = tempfile.mkdtemp(prefix="code_sandbox_")
                os.chdir(temp_dir)
                self._set_resource_limits()
                result = func(*args, **kwargs)
                queue.put(('success', result))
            except ResourceLimitException as e:
                queue.put(('resource_error', str(e)))
            except SecurityViolationException as e:
                queue.put(('security_error', str(e)))
            except Exception:
                queue.put(('exception', traceback.format_exc()))
            finally:
                if temp_dir and os.path.exists(temp_dir):
                    try:
                        shutil.rmtree(temp_dir)
                    except Exception as clean_err:
                        logger.error(f"清理临时目录失败: {clean_err}")
        p = ctx.Process(target=worker, args=(result_queue, *args), kwargs=kwargs)
        p.start()
        try:
            p.join(self.timeout)
            if p.is_alive():
                p.terminate()
                p.join(timeout=1.0)
                if p.is_alive():
                    p.kill()
                    p.join()
                raise TimeoutError(f"执行超时 ({self.timeout}秒)")
            if result_queue.empty():
                raise RuntimeError("工作进程未返回结果")
            status, data = result_queue.get()
            if status == 'success':
                return data
            elif status == 'resource_error':
                raise ResourceLimitException(data)
            elif status == 'security_error':
                raise SecurityViolationException(data)
            else:
                raise Exception(data)
        finally:
            if p.is_alive():
                p.terminate()
                p.join(timeout=0.5)
                if p.is_alive():
                    p.kill()
                    p.join()

    def run_code_block(self, code_str: str, timeout: Optional[int] = None) -> Dict[str, Any]:
        self.execution_count += 1
        exec_id = f"exec-{self.execution_count}"
        logger.info(f"[{exec_id}] 开始执行代码块 (长度: {len(code_str)}字符)")
        if not self._validate_code(code_str):
            return {
                "success": False,
                "output": "",
                "error": "代码验证失败：包含不安全结构",
                "execution_time": 0.0
            }
        actual_timeout = timeout if timeout is not None else self.timeout
        output = io.StringIO()
        error = None
        start_time = time.time()
        execution_time = 0.0
        try:
            safe_env = self._create_safe_environment()
            def sandboxed_exec():
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    exec(code_str, safe_env)
                return output.getvalue()
            result_output = self._run_in_sandbox(sandboxed_exec)
            output.write(result_output)
        except TimeoutError as te:
            error = str(te)
            logger.warning(f"[{exec_id}] 执行超时: {error}")
        except ResourceLimitException as rle:
            error = f"资源限制违规: {rle}"
            logger.warning(f"[{exec_id}] {error}")
        except SecurityViolationException as sve:
            error = f"安全策略违规: {sve}"
            logger.warning(f"[{exec_id}] {error}")
        except Exception as e:
            error = traceback.format_exc()
            logger.error(f"[{exec_id}] 执行异常: {str(e)}")
        finally:
            execution_time = time.time() - start_time
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__
        output_str = self._truncate_output(output.getvalue())
        logger.info(f"[{exec_id}] 执行完成 (状态: {'成功' if error is None else '失败'}, 耗时: {execution_time:.2f}s)")
        return {
            "success": error is None,
            "output": output_str,
            "error": error,
            "execution_time": round(execution_time, 4)
        }

    def run_function_from_file(self, filepath: str, func_name: str, *args, **kwargs) -> Dict[str, Any]:
        exec_id = f"func-{func_name}-{os.getpid()}"
        logger.info(f"[{exec_id}] 开始执行函数: {func_name} from {filepath}")
        output = io.StringIO()
        error = None
        result = None
        start_time = time.time()
        execution_time = 0.0
        try:
            def sandboxed_exec():
                spec = importlib.util.spec_from_file_location("dynamic_module", filepath)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                func = getattr(module, func_name, None)
                if func is None:
                    raise AttributeError(f"模块中未找到函数: {func_name}")
                if not callable(func):
                    raise TypeError(f"{func_name} 不是可调用函数")
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    return func(*args, **kwargs)
            result = self._run_in_sandbox(sandboxed_exec)
        except TimeoutError as te:
            error = str(te)
            logger.warning(f"[{exec_id}] 执行超时: {error}")
        except ResourceLimitException as rle:
            error = f"资源限制违规: {rle}"
            logger.warning(f"[{exec_id}] {error}")
        except SecurityViolationException as sve:
            error = f"安全策略违规: {sve}"
            logger.warning(f"[{exec_id}] {error}")
        except Exception as e:
            error = traceback.format_exc()
            logger.error(f"[{exec_id}] 执行异常: {str(e)}")
        finally:
            execution_time = time.time() - start_time
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__
        output_str = self._truncate_output(output.getvalue())
        logger.info(f"[{exec_id}] 函数执行完成 (状态: {'成功' if error is None else '失败'}, 耗时: {execution_time:.2f}s)")
        return {
            "success": error is None,
            "output": output_str,
            "result": result,
            "error": error,
            "execution_time": round(execution_time, 4)
        }

    def execute_tests(self, test_cases: List[Tuple[str, List[Any], Dict[str, Any]]]) -> Dict[str, Any]:
        session_id = f"test-session-{int(time.time())}"
        logger.info(f"[{session_id}] 开始测试套件: {len(test_cases)}个测试用例")
        results = []
        all_passed = True
        total_time = 0.0
        for i, (func_name, args, kwargs) in enumerate(test_cases, 1):
            test_id = f"{session_id}-{i}"
            test_result = {
                "test_id": test_id,
                "function": func_name,
                "arguments": {"args": args, "kwargs": kwargs},
                "status": "pending"
            }
            try:
                start_time = time.time()
                exec_result = self.run_function_from_file("aicore.py", func_name, *args, **kwargs)
                exec_time = time.time() - start_time
                test_result.update({
                    "status": "passed" if exec_result["success"] else "failed",
                    "output": exec_result["output"],
                    "result": exec_result.get("result"),
                    "error": exec_result.get("error"),
                    "execution_time": round(exec_time, 4)
                })
                total_time += exec_time
                if not exec_result["success"]:
                    all_passed = False
                    logger.warning(f"[{test_id}] 测试失败: {func_name} - {exec_result.get('error', '未知错误')}")
                else:
                    logger.info(f"[{test_id}] 测试通过: {func_name} (耗时: {exec_time:.4f}s)")
            except Exception as e:
                test_result.update({
                    "status": "error",
                    "error": str(e),
                    "execution_time": 0.0
                })
                all_passed = False
                logger.error(f"[{test_id}] 测试执行异常: {func_name} - {e}")
            results.append(test_result)
        logger.info(f"[{session_id}] 测试套件完成: 通过 {sum(1 for r in results if r['status'] == 'passed')}/{len(test_cases)}")
        return {
            "all_passed": all_passed,
            "total_tests": len(test_cases),
            "passed_tests": sum(1 for r in results if r["status"] == "passed"),
            "total_time": round(total_time, 4),
            "details": results
        }

# 模块生命周期接口
def initialize() -> bool:
    logger.info("code_executor模块初始化完成")
    global executor
    executor = CodeExecutor(timeout=15, max_output_length=5000)
    return True

def cleanup() -> bool:
    logger.info("code_executor模块清理完成")
    return True

# 动作接口
def action_run_code_block(core, params: Dict[str, Any]) -> Dict[str, Any]:
    code_str = params.get("code", "")
    timeout = params.get("timeout", None)
    return executor.run_code_block(code_str, timeout)

def action_run_function_from_file(core, params: Dict[str, Any]) -> Dict[str, Any]:
    filepath = params.get("filepath", "")
    func_name = params.get("func_name", "")
    args = params.get("args", [])
    kwargs = params.get("kwargs", {})
    return executor.run_function_from_file(filepath, func_name, *args, **kwargs)

def action_execute_tests(core, params: Dict[str, Any]) -> Dict[str, Any]:
    test_cases = params.get("test_cases", [])
    return executor.execute_tests(test_cases)

def register_actions(dispatcher):
    logger.info("注册代码执行模块动作")
    dispatcher.register_action(
        "run_code",
        action_run_code_block,
        description="安全执行Python代码块 (Fedora沙箱)",
        parameters={
            "code": {"type": "string", "description": "要执行的Python代码"},
            "timeout": {"type": "integer", "description": "执行超时时间(秒)", "optional": True}
        },
        module_name="code_executor.module"
    )
    dispatcher.register_action(
        "run_function",
        action_run_function_from_file,
        description="执行文件中的Python函数 (Fedora沙箱)",
        parameters={
            "filepath": {"type": "string", "description": "包含函数的文件路径"},
            "func_name": {"type": "string", "description": "要执行的函数名"},
            "args": {"type": "array", "description": "函数位置参数", "optional": True},
            "kwargs": {"type": "object", "description": "函数关键字参数", "optional": True}
        },
        module_name="code_executor.module"
    )
    dispatcher.register_action(
        "run_tests",
        action_execute_tests,
        description="执行测试用例 (Fedora安全环境)",
        parameters={
            "test_cases": {
                "type": "array",
                "description": "测试用例列表，每个元素为 [函数名, 位置参数列表, 关键字参数字典]",
                "items": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 3
                }
            }
        },
        module_name="code_executor.module"
    )

if __name__ == "__main__":
    print("=== code_executor模块独立测试启动 ===")
    initialize()
    test_code = "print('Hello 三花聚顶!')"
    res = executor.run_code_block(test_code)
    print("执行结果:", res)
