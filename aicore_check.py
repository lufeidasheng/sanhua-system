#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import json
import logging

from core.aicore import ExtensibleAICore
from core.aicore.config import AICoreConfig
from core.aicore.health_monitor import HealthMonitorPlus


logging.basicConfig(level=logging.INFO)
log = logging.getLogger("aicore_check")

def check_config(config: AICoreConfig):
    log.info("🔍 检查配置...")
    # 验证身份配置
    if not config.identity.get("assistant"):
        log.error("⚠️ 助手名称为空！")
        return False

    # 验证后端配置
    if not config.backends:
        log.error("⚠️ 后端配置为空！")
        return False

    enabled_backends = [b for b in config.backends if b.enabled]
    if not enabled_backends:
        log.error("⚠️ 没有启用的后端！")
        return False

    log.info("✅ 配置检查通过！")
    return True

def check_backend_registration(aicore: ExtensibleAICore):
    log.info("🔍 检查后端模块注册...")
    backends = aicore.backend_manager.backends
    if not backends:
        log.error("⚠️ 没有注册任何后端模块！")
        return False

    # 检查每个后端是否能正常工作
    for backend_name, backend in backends.items():
        if not backend.health_check():
            log.error(f"⚠️ 后端 {backend_name} 无法通过健康检查！")
            return False
    log.info("✅ 后端模块注册检查通过！")
    return True

def check_health(aicore: ExtensibleAICore):
    log.info("🔍 检查健康监控...")
    health_status = aicore.health_monitor.get_health_status()
    if health_status != "healthy":
        log.error(f"⚠️ 健康状态异常: {health_status}")
        return False
    log.info("✅ 健康状态正常！")
    return True

def check_logs(aicore: ExtensibleAICore):
    log.info("🔍 检查最近日志...")
    logs = aicore.controller.recent_logs("stderr", 20)
    if logs:
        log.info("📜 最近日志:")
        for line in logs:
            log.info(line)
    else:
        log.info("📜 没有日志输出，可能是正常的。")
    return True

def check_system_status(aicore: ExtensibleAICore):
    log.info("🔍 检查系统状态...")
    status = aicore.get_status()
    log.info(f"系统状态: {json.dumps(status, indent=2, ensure_ascii=False)}")
    return True

def check_backend_switch(aicore: ExtensibleAICore):
    log.info("🔍 检查后端切换功能...")
    current_backend = aicore.backend_manager.active_backend
    log.info(f"当前活跃后端: {current_backend}")
    
    # 尝试切换到下一个可用后端
    next_backend = aicore.backend_manager.get_next_available_backend()
    if next_backend:
        log.info(f"切换到后端: {next_backend}")
        aicore.backend_manager.switch_backend(next_backend)
        log.info(f"切换成功，当前后端: {aicore.backend_manager.active_backend}")
    else:
        log.error("⚠️ 没有可用的后端进行切换！")
        return False
    return True

def run_check():
    # 加载配置
    config = AICoreConfig.from_env()

    # 创建AICore实例
    aicore = ExtensibleAICore(config)
    
    # 检查步骤
    if not check_config(config):
        return
    if not check_backend_registration(aicore):
        return
    if not check_health(aicore):
        return
    if not check_logs(aicore):
        return
    if not check_system_status(aicore):
        return
    if not check_backend_switch(aicore):
        return
    
    log.info("✅ 所有检查通过！系统运行正常。")

if __name__ == "__main__":
    run_check()
