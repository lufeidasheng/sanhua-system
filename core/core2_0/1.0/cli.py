#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import cmd
import shlex
import json
import logging
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any

from core.core2_0.action_dispatcher import get_global_dispatcher, execute_action, list_actions
from core.core2_0.module_loader import ModuleLoader
from core.core2_0.event_bus import init_event_bus, get_event_bus

# 配置基础日志格式（后续会覆盖日志等级）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("三花聚顶-CLI")


class ApplicationCLI(cmd.Cmd):
    """三花聚顶模块化系统命令行界面"""

    intro = """
    欢迎使用 三花聚顶 模块化系统
    版本: 2.0
    输入 help 查看可用命令
    """
    prompt = "三花> "

    def __init__(self, module_loader: ModuleLoader, dispatcher: Any, event_bus: Any):
        super().__init__()
        self.module_loader = module_loader
        self.dispatcher = dispatcher
        self.event_bus = event_bus
        self.loop = self._setup_event_loop()
        self._register_system_commands()
        self._initialize_system()

    def _setup_event_loop(self) -> asyncio.AbstractEventLoop:
        """初始化事件循环，兼容不同Python版本和环境"""
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            return loop
        except Exception as e:
            logger.error("事件循环初始化失败: %s", str(e), exc_info=True)
            raise RuntimeError(f"无法初始化事件循环: {str(e)}")

    def _initialize_system(self) -> None:
        """系统初始化流程：注册事件，加载模块，发布系统就绪事件"""
        try:
            self._register_system_events()
            loaded, failed = self.module_loader.load_all_modules()

            logger.info("系统初始化完成，成功加载 %d 个模块，失败 %d 个模块", loaded, failed)
            print(f"系统就绪，成功加载 {loaded} 个模块，失败 {failed} 个模块")

            if self.event_bus and hasattr(self.event_bus, 'emit'):
                self.event_bus.emit("system_ready", {"loaded": loaded, "failed": failed})

        except Exception as e:
            logger.critical("系统初始化失败: %s", str(e), exc_info=True)
            print(f"系统初始化失败: {str(e)}")
            self._safe_shutdown()
            sys.exit(1)

    def _register_system_commands(self) -> None:
        self.aliases = {
            'ls': 'modules',
            'list': 'modules',
            'quit': 'exit',
            '?': 'help',
            'cls': 'clear'
        }

    def _register_system_events(self) -> None:
        if not self.event_bus or not hasattr(self.event_bus, 'subscribe'):
            logger.warning("事件总线不可用，系统事件监听未注册")
            return

        def handle_module_loaded(payload):
            module_name = payload.get("module_name") if isinstance(payload, dict) else str(payload)
            logger.info("模块加载事件: %s", module_name)
            print(f"⚡ 模块 {module_name} 加载完成")

        def handle_module_error(payload):
            if isinstance(payload, dict):
                module_name = payload.get("module_name", "未知模块")
                error = payload.get("error", "未知错误")
            else:
                module_name, error = "未知模块", str(payload)
            logger.error("模块错误: %s - %s", module_name, error)
            print(f"⚠️ 模块 {module_name} 加载失败: {error}")

        self.event_bus.subscribe('module_loaded', handle_module_loaded)
        self.event_bus.subscribe('module_error', handle_module_error)
        logger.info("系统事件监听注册完成")

    def _safe_shutdown(self) -> None:
        try:
            if hasattr(self, 'loop') and self.loop and not self.loop.is_closed():
                self.loop.close()
        except Exception as e:
            logger.error("关闭事件循环失败: %s", str(e), exc_info=True)

    def default(self, line: str) -> bool:
        """处理未知命令，支持命令别名"""
        cmd, _, arg = line.partition(' ')
        if cmd in self.aliases:
            return self.onecmd(f"{self.aliases[cmd]} {arg}")
        print(f"未知命令: {cmd}。输入 help 查看可用命令")
        return False

    def emptyline(self) -> None:
        """空行处理，避免重复执行上一条命令"""
        pass

    # ------------- 模块管理命令 -------------

    def do_load(self, arg: str) -> None:
        """加载模块: load <模块名> [路径]"""
        args = shlex.split(arg)
        if not args:
            print("错误：请提供模块名")
            return
        module_name = args[0]
        module_path = args[1] if len(args) > 1 else None
        try:
            if module_path and hasattr(self.module_loader, "load_module_from_path"):
                result = self.module_loader.load_module_from_path(module_name, module_path)
            else:
                result = self.module_loader.load_module(module_name)
            if result:
                print(f"✅ 模块 '{module_name}' 加载成功")
                logger.info("成功加载模块: %s", module_name)
            else:
                print(f"❌ 模块 '{module_name}' 加载失败")
                logger.warning("加载模块失败: %s", module_name)
        except Exception as e:
            logger.error("加载模块异常: %s", str(e), exc_info=True)
            print(f"加载模块出错: {str(e)}")

    def do_unload(self, arg: str) -> None:
        """卸载模块: unload <模块名>"""
        if not arg:
            print("错误：请提供模块名")
            return
        module_name = arg.strip()
        try:
            module = self.module_loader.get_module(module_name)
            if module and hasattr(module, 'shutdown') and callable(module.shutdown):
                module.shutdown()
            if self.module_loader.unload_module(module_name):
                print(f"✅ 模块 '{module_name}' 卸载成功")
                logger.info("成功卸载模块: %s", module_name)
            else:
                print(f"❌ 模块 '{module_name}' 卸载失败")
                logger.warning("卸载模块失败: %s", module_name)
        except Exception as e:
            logger.error("卸载模块异常: %s", str(e), exc_info=True)
            print(f"卸载模块出错: {str(e)}")

    def do_reload(self, arg: str) -> None:
        """重载模块: reload <模块名>"""
        if not arg:
            print("错误：请提供模块名")
            return
        module_name = arg.strip()
        try:
            if self.module_loader.reload_module(module_name):
                print(f"✅ 模块 '{module_name}' 重载成功")
                logger.info("成功重载模块: %s", module_name)
            else:
                print(f"❌ 模块 '{module_name}' 重载失败")
                logger.warning("重载模块失败: %s", module_name)
        except Exception as e:
            logger.error("重载模块异常: %s", str(e), exc_info=True)
            print(f"重载模块出错: {str(e)}")

    def do_modules(self, arg: str) -> None:
        """列出模块: modules [all]"""
        show_all = arg.strip().lower() == 'all'
        modules = self.module_loader.list_modules(loaded_only=not show_all)
        if not modules:
            print("⚠️ 没有找到模块" if show_all else "⚠️ 没有已加载的模块")
            return
        title = "所有可用模块" if show_all else "已加载模块"
        print(f"\n{title} (共 {len(modules)} 个):")
        print("-" * 60)
        for idx, name in enumerate(modules, 1):
            mod = self.module_loader.get_module(name)
            status = "🟢" if self.module_loader.is_module_loaded(name) else "⚪"
            ver = getattr(mod, "__version__", "未知")
            desc = getattr(mod, "__description__", "无描述")
            print(f"{idx:2d}. {status} {name} (v{ver})")
            print(f"    {desc}")
            print("-" * 60)

    # ------------- 动作管理命令 -------------

    def do_actions(self, arg: str) -> None:
        """列出动作: actions [模块名]"""
        filter_module = arg.strip() if arg else None
        try:
            actions = list_actions()
        except Exception as e:
            print(f"⚠️ 获取动作失败: {e}")
            logger.error("获取动作列表失败: %s", str(e), exc_info=True)
            return

        if not actions:
            print("⚠️ 没有注册的动作")
            return

        filtered = [a for a in actions if not filter_module or a.get('module') == filter_module]

        if not filtered:
            print(f"⚠️ 模块 '{filter_module}' 中没有找到动作")
            return

        title = f"所有注册动作 ({len(filtered)} 个)"
        if filter_module:
            title += f" [模块: {filter_module}]"

        print(f"\n{title}:")
        print("-" * 80)
        for idx, meta in enumerate(filtered, 1):
            name = meta.get('name', '未知动作')
            mod = meta.get('module', '未知模块')
            desc = meta.get('description', '无描述')
            sig = meta.get('signature', '无参数信息')
            print(f"{idx:2d}. 🔹 {name}")
            print(f"    模块: {mod}")
            print(f"    描述: {desc}")
            print(f"    签名: {sig}")
            print("-" * 80)

    def do_call(self, arg: str) -> None:
        """调用动作: call <动作名> [参数...]"""
        args = shlex.split(arg)
        if not args:
            print("错误：请提供动作名")
            return

        action_name = args[0]
        action_args = []
        for a in args[1:]:
            try:
                action_args.append(json.loads(a))
            except json.JSONDecodeError:
                action_args.append(a)

        try:
            logger.info("执行动作: %s 参数: %s", action_name, action_args)
            print(f"🔄 正在执行动作: {action_name}...")

            coro_or_result = execute_action(action_name, *action_args)

            if asyncio.iscoroutine(coro_or_result):
                result = self.loop.run_until_complete(coro_or_result)
            else:
                result = coro_or_result

            print("\n✅ 动作执行成功！")
            print("=" * 60)
            if isinstance(result, (dict, list)):
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print(str(result))
            print("=" * 60)

        except Exception as e:
            logger.error("执行动作异常: %s", str(e), exc_info=True)
            print(f"\n❌ 动作执行失败: {str(e)}")

    # ------------- 其他系统命令 -------------

    def do_clear(self, arg: str) -> None:
        """清屏: clear"""
        os.system('cls' if os.name == 'nt' else 'clear')

    def do_status(self, arg: str) -> None:
        """系统状态: status"""
        loaded = len(self.module_loader.list_modules(loaded_only=True))
        total = len(self.module_loader.list_modules(loaded_only=False))
        try:
            actions = list_actions()
        except Exception:
            actions = []
        print("\n📊 系统状态:")
        print("-" * 40)
        print(f"已加载模块: {loaded}/{total}")
        print(f"注册动作: {len(actions)} 个")
        print(f"Python版本: {sys.version.split()[0]}")
        print(f"运行平台: {sys.platform}")
        print("-" * 40)

    def do_exit(self, arg: str) -> bool:
        """退出系统: exit"""
        print("\n🛑 正在关闭系统...")
        try:
            # 关闭所有模块的资源
            for mod_name in self.module_loader.list_modules(loaded_only=True):
                try:
                    module = self.module_loader.get_module(mod_name)
                    if module and hasattr(module, 'shutdown') and callable(module.shutdown):
                        module.shutdown()
                except Exception as e:
                    logger.error("关闭模块 %s 失败: %s", mod_name, str(e), exc_info=True)

            # 关闭模块加载器
            self.module_loader.shutdown()

            # 关闭事件循环
            if hasattr(self, 'loop') and self.loop and not self.loop.is_closed():
                self.loop.close()

            print("✅ 系统已安全关闭")
            logger.info("系统正常退出")
        except Exception as e:
            logger.error("系统关闭异常: %s", str(e), exc_info=True)
            print(f"❌ 关闭时出错: {str(e)}")
        finally:
            print("👋 再见！")
            return True

    def do_help(self, arg: str) -> None:
        """显示帮助: help [命令]"""
        if arg:
            super().do_help(arg)
            return

        print("\n📖 三花聚顶 CLI 帮助")
        print("=" * 60)
        print("模块管理命令:")
        print("  load <模块名> [路径]  - 加载模块")
        print("  unload <模块名>       - 卸载模块")
        print("  reload <模块名>       - 重载模块")
        print("  modules [all]         - 列出模块")
        print("\n动作管理命令:")
        print("  actions [模块名]      - 列出动作")
        print("  call <动作名> [...]   - 调用动作")
        print("\n系统命令:")
        print("  clear                 - 清屏")
        print("  status                - 系统状态")
        print("  exit                  - 退出系统")
        print("  help                  - 显示帮助")
        print("\n提示: 可以使用 'ls' 代替 'modules', '?' 代替 'help'")
        print("=" * 60)


def _parse_env_vars() -> Dict[str, Any]:
    """解析环境变量，支持配置模块目录、安全检查、热重载、日志等级"""
    module_dir = Path(os.getenv("MODULES_DIR", "modules"))
    security_check = os.getenv("MODULE_LOADER_SECURITY_CHECK", "true").lower() in ("true", "1", "yes", "on")
    hot_reload = os.getenv("MODULE_HOT_RELOAD", "true").lower() in ("true", "1", "yes", "on")
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    return {
        'module_dir': module_dir,
        'security_check': security_check,
        'hot_reload': hot_reload,
        'log_level': log_level,
    }


def main() -> None:
    """三花聚顶 CLI 主入口"""
    try:
        env = _parse_env_vars()

        if not env['module_dir'].exists():
            raise FileNotFoundError(f"模块目录不存在: {env['module_dir']}")

        logging.getLogger().setLevel(env['log_level'])

        dispatcher = get_global_dispatcher()

        event_bus = init_event_bus({
            'thread_pool_size': 10,
            'max_listeners': 100,
        })

        loader = ModuleLoader(
            modules_dir=str(env['module_dir']),
            dispatcher=dispatcher,
            event_bus=event_bus,
            security_check=env['security_check'],
            enable_hotreload=env['hot_reload'],
            log_level=env['log_level']
        )

        cli = ApplicationCLI(loader, dispatcher, event_bus)
        cli.cmdloop()

    except Exception as e:
        logger.critical("系统启动失败: %s", str(e), exc_info=True)
        print(f"💥 系统启动失败: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
