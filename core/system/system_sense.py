#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
三花聚顶 · System Sense

统一的系统监控后端：
- CPU 使用率
- Load Average
- 内存使用率 / 已用 / 总量
- 根分区磁盘使用率
- 磁盘读写累计（MB）
- 网络上下行累计（MB）
- 网络丢包 in/out

兼容历史接口：
- SystemSense.get_system_info()  → aicore 监控线程使用
同时提供：
- get_system_health()           → 给 GUI / 动作系统直接调用
"""

from __future__ import annotations

import os
import platform
from typing import Any, Dict, List

import psutil  # type: ignore

from core.core2_0.sanhuatongyu.logger import get_logger

log = get_logger(__name__)

MB = 1024 * 1024


def _safe_get_loadavg() -> str:
    """
    跨平台安全获取 Load Average。
    Windows 上没有 loadavg，直接返回 N/A。
    """
    try:
        if hasattr(os, "getloadavg"):
            l1, l5, l15 = os.getloadavg()
            return f"{l1:.1f}/{l5:.1f}/{l15:.1f}"
        else:
            return "N/A"
    except Exception as e:
        log.debug(f"获取 loadavg 失败: {e}")
        return "N/A"


def _format_bytes_mb(value: int | float) -> str:
    return f"{value / MB:.1f}"


def get_system_health(modules_count: int | None = None) -> Dict[str, Any]:
    """
    新版统一接口：返回系统健康信息，给 GUI / 动作系统使用。

    :param modules_count: 可选，外部可传入当前“已接入模块数”，不传则用 0。
    :return: dict，包含 status / modules / metrics 列表。
    """
    try:
        # ---------- CPU ----------
        cpu_percent = psutil.cpu_percent(interval=0.2)

        # ---------- Load Avg ----------
        load_avg_str = _safe_get_loadavg()

        # ---------- 内存 ----------
        mem = psutil.virtual_memory()
        mem_percent = mem.percent
        mem_used_gb = mem.used / 1024**3
        mem_total_gb = mem.total / 1024**3

        # ---------- 磁盘 ----------
        # 默认根分区；如果你有专用数据盘可以改为 '/mnt/data' 等
        try:
            disk = psutil.disk_usage("/")
            disk_percent = disk.percent
        except Exception as e:
            log.debug(f"获取根分区磁盘使用失败: {e}")
            disk_percent = 0.0

        try:
            disk_io = psutil.disk_io_counters()
            disk_read_mb = _format_bytes_mb(disk_io.read_bytes)
            disk_write_mb = _format_bytes_mb(disk_io.write_bytes)
        except Exception as e:
            log.debug(f"获取磁盘 IO 失败: {e}")
            disk_read_mb = "0.0"
            disk_write_mb = "0.0"

        # ---------- 网络 ----------
        try:
            net_io = psutil.net_io_counters()
            net_up_mb = _format_bytes_mb(net_io.bytes_sent)
            net_down_mb = _format_bytes_mb(net_io.bytes_recv)
            drop_in = net_io.dropin
            drop_out = net_io.dropout
        except Exception as e:
            log.debug(f"获取网络 IO 失败: {e}")
            net_up_mb = "0.0"
            net_down_mb = "0.0"
            drop_in = 0
            drop_out = 0

        # ---------- 健康状态 ----------
        status = "OK"
        # 如需告警阈值，可以在这里加，例如：
        # if cpu_percent > 90 or mem_percent > 90:
        #     status = "WARN"

        metrics: List[Dict[str, str]] = [
            {"name": "CPU 使用率", "value": f"{cpu_percent:.1f}%"},
            {"name": "Load Avg", "value": load_avg_str},
            {"name": "内存 使用率", "value": f"{mem_percent:.1f}%"},
            {
                "name": "内存 已用/可用",
                "value": f"{mem_used_gb:.1f} / {mem_total_gb:.1f} GB",
            },
            {"name": "磁盘 使用率", "value": f"{disk_percent:.1f}%"},
            {
                "name": "磁盘 读/写(MB)",
                "value": f"{disk_read_mb} / {disk_write_mb}",
            },
            {
                "name": "网络 上+下(MB)",
                "value": f"{net_up_mb} / {net_down_mb}",
            },
            {
                "name": "网络 丢包(in/out)",
                "value": f"{drop_in} / {drop_out}",
            },
        ]

        return {
            "status": status,
            "modules": modules_count if modules_count is not None else 0,
            "metrics": metrics,
            "platform": platform.platform(),
        }

    except Exception as e:
        # 出错时不要让 GUI / 监控线程崩，返回一个 ERROR 状态
        log.error(f"获取系统健康数据失败: {e}", exc_info=True)
        return {
            "status": "ERROR",
            "modules": modules_count if modules_count is not None else 0,
            "metrics": [],
            "error": str(e),
        }


# ========== 兼容旧接口 ==========
class SystemSense:
    """
    兼容老版本 aicore 使用的接口：

        info = system_sense.SystemSense.get_system_info()

    现在直接委托给 get_system_health()。
    """

    @staticmethod
    def get_system_info(modules_count: int | None = None) -> Dict[str, Any]:
        return get_system_health(modules_count=modules_count)