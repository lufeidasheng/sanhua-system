#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
系统控制动作模块
- 重启 / 关机
- 网络重启
- 打开网址 / 文件
- 播放视频
- 蓝牙开关与设备连接

可直接挂到 QuantumActionDispatcher / AICore 作为系统级动作。
"""

import os
import subprocess
from typing import List

from core.core2_0.sanhuatongyu.logger import get_logger

log = get_logger(__name__)

# ================== 内部工具函数 ==================


def _run_cmd(
    cmd: List[str],
    *,
    timeout: int = 30,
    check: bool = True,
    log_prefix: str = "",
) -> subprocess.CompletedProcess:
    """
    统一封装 subprocess.run，带超时与统一日志。
    """
    try:
        log.debug(f"{log_prefix}执行命令: {cmd}")
        result = subprocess.run(
            cmd,
            check=check,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        if result.stdout:
            log.debug(f"{log_prefix}stdout: {result.stdout.strip()}")
        if result.stderr:
            log.debug(f"{log_prefix}stderr: {result.stderr.strip()}")
        return result
    except subprocess.CalledProcessError as e:
        log.error(
            f"{log_prefix}命令执行失败: {cmd}, returncode={e.returncode}, "
            f"stderr={getattr(e, 'stderr', '')}"
        )
        raise
    except subprocess.TimeoutExpired as e:
        log.error(f"{log_prefix}命令执行超时: {cmd}, timeout={timeout}s")
        raise
    except FileNotFoundError as e:
        log.error(f"{log_prefix}命令不存在: {cmd[0]} ({e})")
        raise


# ================== 系统电源控制 ==================


def reboot_system() -> str:
    """
    优先调用自定义脚本 /home/lufei/restart.sh（非交互 sudo），失败则回落 systemctl reboot。
    """
    script_path = "/home/lufei/restart.sh"

    # 1) 优先通过脚本重启（如果存在且可执行）
    if os.path.isfile(script_path) and os.access(script_path, os.X_OK):
        try:
            _run_cmd(
                ["sudo", "-n", script_path],
                timeout=20,
                log_prefix="[reboot_system/script] ",
            )
            log.info("通过脚本重启系统")
            return "系统正在通过脚本重启。"
        except Exception:
            log.warning("脚本重启失败，尝试使用 systemctl 重启")

    # 2) 回落到 systemctl reboot
    try:
        _run_cmd(
            ["systemctl", "reboot"],
            timeout=20,
            log_prefix="[reboot_system/systemctl] ",
        )
        log.info("系统正在重启")
        return "系统正在重启。"
    except Exception as e:
        log.error(f"重启失败: {e}")
        return f"重启失败: {e}"


def shutdown_system() -> str:
    """
    通过 systemctl 关机。
    """
    try:
        _run_cmd(
            ["systemctl", "poweroff"],
            timeout=20,
            log_prefix="[shutdown_system] ",
        )
        log.info("系统正在关机")
        return "系统正在关机。"
    except Exception as e:
        log.error(f"关机失败: {e}")
        return f"关机失败: {e}"


# ================== 网络控制 ==================


def restart_network() -> str:
    """
    使用 nmcli 重启 NetworkManager 管理的网络。
    """
    try:
        _run_cmd(
            ["nmcli", "networking", "off"],
            timeout=10,
            log_prefix="[restart_network] ",
        )
        _run_cmd(
            ["nmcli", "networking", "on"],
            timeout=10,
            log_prefix="[restart_network] ",
        )
        log.info("网络重启成功")
        return "网络已成功重启。"
    except Exception as e:
        log.error(f"网络重启失败: {e}")
        return f"网络重启失败: {e}"


# ================== 文件 / URL / 视频 ==================


def open_url(url: str) -> str:
    """
    使用 xdg-open 打开 URL。
    """
    try:
        subprocess.Popen(
            ["xdg-open", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.info(f"打开网址: {url}")
        return f"已打开网址：{url}"
    except Exception as e:
        log.error(f"打开网址失败: {e}")
        return f"打开网址失败: {e}"


def play_movie(name: str) -> str:
    """
    在 ~/Videos 中查找匹配名称的视频文件，并使用 mpv 播放。
    - 支持常见扩展名：.mp4 / .mkv / .mov / .avi
    """
    try:
        videos_dir = os.path.expanduser("~/Videos")
        candidates = [
            os.path.join(videos_dir, f"{name}{ext}")
            for ext in (".mp4", ".mkv", ".mov", ".avi")
        ]

        path = None
        for p in candidates:
            if os.path.exists(p):
                path = p
                break

        if path is None:
            log.error(f"电影文件不存在（已尝试）：{candidates}")
            return f"电影文件不存在: {name}"

        subprocess.Popen(
            ["mpv", path, "--no-terminal"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.info(f"播放电影: {path}")
        return f"正在播放电影: {name}"
    except Exception as e:
        log.error(f"播放电影失败: {e}")
        return f"播放电影失败: {e}"


def open_file(path: str) -> str:
    """
    使用 xdg-open 打开文件或目录。
    """
    try:
        full_path = os.path.expanduser(path)
        if not os.path.exists(full_path):
            log.error(f"文件不存在: {full_path}")
            return f"文件不存在: {full_path}"

        subprocess.Popen(
            ["xdg-open", full_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.info(f"打开文件: {full_path}")
        return f"已打开文件: {full_path}"
    except Exception as e:
        log.error(f"打开文件失败: {e}")
        return f"打开文件失败: {e}"


# ================== 蓝牙控制 ==================


def bluetooth_on() -> str:
    """
    通过 rfkill 打开蓝牙。
    """
    try:
        _run_cmd(
            ["rfkill", "unblock", "bluetooth"],
            timeout=10,
            log_prefix="[bluetooth_on] ",
        )
        log.info("蓝牙已打开")
        return "蓝牙已打开。"
    except Exception as e:
        log.error(f"打开蓝牙失败: {e}")
        return f"打开蓝牙失败: {e}"


def bluetooth_off() -> str:
    """
    通过 rfkill 关闭蓝牙。
    """
    try:
        _run_cmd(
            ["rfkill", "block", "bluetooth"],
            timeout=10,
            log_prefix="[bluetooth_off] ",
        )
        log.info("蓝牙已关闭")
        return "蓝牙已关闭。"
    except Exception as e:
        log.error(f"关闭蓝牙失败: {e}")
        return f"关闭蓝牙失败: {e}"


def connect_bluetooth_device(device_mac: str) -> str:
    """
    使用 bluetoothctl 尝试连接指定 MAC 的设备。
    - 自动执行：power on / agent on / default-agent / scan on / pair / connect / scan off / exit
    """
    try:
        cmds = (
            "power on\n"
            "agent on\n"
            "default-agent\n"
            "scan on\n"
            f"pair {device_mac}\n"
            f"connect {device_mac}\n"
            "scan off\n"
            "exit\n"
        )

        log.info(f"开始连接蓝牙设备: {device_mac}")
        process = subprocess.Popen(
            ["bluetoothctl"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = process.communicate(cmds, timeout=20)

        # 日志里只保留前几行，避免输出过长
        if stdout:
            log.debug(
                "蓝牙连接 stdout 前 500 字符: "
                f"{stdout[:500].replace(os.linesep, ' ')}"
            )
        if stderr:
            log.debug(
                "蓝牙连接 stderr 前 500 字符: "
                f"{stderr[:500].replace(os.linesep, ' ')}"
            )

        if process.returncode == 0:
            log.info(f"已发送蓝牙连接命令，目标设备: {device_mac}")
            return f"尝试连接蓝牙设备：{device_mac}"
        else:
            log.error(f"蓝牙连接失败（返回码 {process.returncode}）: {stderr}")
            return f"连接蓝牙设备失败：{stderr or '未知错误'}"
    except subprocess.TimeoutExpired:
        log.error("连接蓝牙设备超时，bluetoothctl 无响应")
        return "连接蓝牙设备超时，请检查设备是否在配对模式下。"
    except FileNotFoundError as e:
        log.error(f"bluetoothctl 不存在: {e}")
        return "系统未安装 bluetoothctl，无法连接蓝牙设备。"
    except Exception as e:
        log.error(f"连接蓝牙设备异常: {e}")
        return f"连接蓝牙设备异常: {e}"