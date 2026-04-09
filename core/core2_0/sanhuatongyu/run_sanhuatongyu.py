#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import sys
import time
import traceback

from .logger import configure_logging, get_logger, I18nManager
from . import SanHuaTongYu
from .entry_dispatcher import EnterpriseEntryDispatcher, CriticalEntryFailure, SecurityException

# 尝试导入 selinux
try:
    import selinux
    SELINUX_AVAILABLE = True
except ImportError:
    SELINUX_AVAILABLE = False

def main():
    # === 1. 配置全局日志与多语言 ===
    configure_logging(
        level="INFO",
        log_dir="logs",
        i18n_lang='zh_CN',
        json_format=True
    )
    logger = get_logger("core_launcher")

    # === 2. 预加载 i18n（可选自定义目录）===
    I18nManager.set_language('zh_CN')

    try:
        # === 3. 解析启动参数 ===
        parser = argparse.ArgumentParser(description="三花统御企业级系统")
        parser.add_argument(
            '--entry', choices=['cli', 'gui', 'voice', 'api', 'emergency'],
            default=os.getenv('APP_ENTRY', 'voice'),
            help="系统入口点"
        )
        parser.add_argument('--dev', action='store_true', help="开发模式")
        parser.add_argument('--global-config', default='config/global.yaml', help="全局配置文件路径")
        parser.add_argument('--user-config', default='config/user.yaml', help="用户配置文件路径")
        parser.add_argument('--timeout', type=int, default=30, help="入口执行超时时间 (秒)")
        parser.add_argument(
            '--fallback-strategy',
            choices=['priority', 'sequence', 'circuit_breaker'],
            default='priority',
            help="企业级回退策略"
        )
        args = parser.parse_args()

        # === 4. 校验配置路径、模块路径 ===
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
        modules_dir = os.path.join(root_dir, 'modules')
        logger.info("system_start_init", extra={
            'entry': args.entry,
            'modules_dir': modules_dir,
            'fallback_strategy': args.fallback_strategy,
            'timeout': args.timeout
        })

        if not os.path.isfile(args.global_config):
            raise FileNotFoundError(f"全局配置文件不存在: {args.global_config}")
        if not os.path.isfile(args.user_config):
            raise FileNotFoundError(f"用户配置文件不存在: {args.user_config}")
        if not os.path.isdir(modules_dir):
            raise FileNotFoundError(f"模块目录不存在: {modules_dir}")

        # === 5. 创建三花统御系统实例 ===
        system = SanHuaTongYu(
            modules_dir=modules_dir,
            global_config_path=args.global_config,
            user_config_path=args.user_config,
            dev_mode=args.dev
        )

        # === 6. SELinux 检查 ===
        selinux_enabled = False
        if SELINUX_AVAILABLE:
            try:
                selinux_enabled = selinux.is_selinux_enabled()
            except Exception as e:
                logger.warning("selinux_check_failed", extra={"error": str(e)})

        # === 7. 创建企业级入口调度器 ===
        dispatcher = EnterpriseEntryDispatcher(
            system=system,
            entry_name=args.entry,
            fallback_strategy=args.fallback_strategy,
            policy_check=(not args.dev) and selinux_enabled,
            timeout=args.timeout
        )

        # === 8. 注册自定义入口 ===
        EnterpriseEntryDispatcher.register_entry("api", "rest_api_entry", priority=95)
        EnterpriseEntryDispatcher.register_entry("emergency", "emergency_cli", priority=0)

        # === 9. 绑定入口调度 ===
        dispatcher.attach()

        # === 10. 启动系统核心流程 ===
        logger.info("starting_module_loader")
        system.run(args.entry)

        logger.info("system_startup_time", extra={"seconds": system.get_uptime()})

        # === 11. 主线程等待系统运行 ===
        while system.is_running:
            time.sleep(1)

    except CriticalEntryFailure as cef:
        logger.critical("critical_entry_failure", extra={"error": str(cef)}, exc_info=True)
        sys.exit(2)
    except SecurityException as se:
        logger.error("security_violation", extra={"error": str(se)}, exc_info=True)
        sys.exit(3)
    except KeyboardInterrupt:
        logger.info("system_shutdown_by_user")
        sys.exit(0)
    except Exception as e:
        logger.critical("system_start_failed", extra={"error": str(e), "trace": traceback.format_exc()}, exc_info=True)
        sys.exit(1)
    finally:
        if 'system' in locals() and system.is_running:
            try:
                system.shutdown()
            except Exception as e:
                logger.error("system_shutdown_failed", extra={"error": str(e)})

if __name__ == '__main__':
    main()
