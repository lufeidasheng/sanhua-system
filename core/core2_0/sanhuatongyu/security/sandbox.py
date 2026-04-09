import docker
import traceback
import time
from .security_manager import SecurityManager

class ModuleSandbox:
    """三花聚顶 · 容器化模块沙箱（融合安全风控&审计）"""

    def __init__(self, module_path: str, module_name: str, user: str = "system"):
        self.client = docker.from_env()
        self.module_path = module_path
        self.module_name = module_name
        self.user = user
        self.security = SecurityManager()  # 建议注入全局单例

    def run(self, command: str, action: str = "run_script", timeout: int = 10, mem_limit: str = '100m'):
        """以容器沙箱执行，并结合三花聚顶安全审计"""
        allowed, reason = self.security.check_access(self.module_name, action, user=self.user)
        log_entry = {
            "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
            "module": self.module_name,
            "action": action,
            "command": command,
            "user": self.user
        }
        if not allowed:
            self.security._log_access(self.module_name, action, False, self.user, f"沙箱拒绝：{reason}")
            raise PermissionError(f"模块沙箱拒绝执行：{reason}")

        try:
            result = self.client.containers.run(
                image='python:3.10-slim',
                command=command,
                volumes={self.module_path: {'bind': '/module', 'mode': 'ro'}},
                working_dir='/module',
                network_mode='none',
                mem_limit=mem_limit,
                remove=True,
                detach=False,
                stdout=True,
                stderr=True,
                user="1000:1000",  # 非root执行
                timeout=timeout
            )
            self.security._log_access(self.module_name, action, True, self.user)
            return result
        except docker.errors.ContainerError as e:
            self.security._log_access(self.module_name, action, False, self.user, f"容器错误: {str(e)}")
            raise RuntimeError(f"沙箱容器执行失败: {e.stderr.decode(errors='ignore') if hasattr(e, 'stderr') else str(e)}")
        except Exception as e:
            tb = traceback.format_exc()
            self.security._log_access(self.module_name, action, False, self.user, f"未知异常: {str(e)}")
            raise RuntimeError(f"沙箱未知异常: {str(e)}\n{tb}")
