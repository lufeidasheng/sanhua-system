#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import subprocess
import datetime
import webbrowser
import threading
from typing import Any, Dict, Optional

from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER


def ensure_dict(val: Any) -> Dict[str, Any]:
    """确保参数为 dict，避免 None 或 str 类型导致调用崩溃"""
    return val if isinstance(val, dict) else {}


class ActionMapper:
    """
    企业对齐版 ActionMapper：
    - 所有动作统一签名：action(context=None, query=None, params=None, **kwargs)
    - 注册动作时写入 extra 治理字段：risk / need_confirm / tags / permission
    - 默认将高风险 OS 动作标记为 need_confirm=True（由 AICore 消费 dispatcher.meta 做确认流）
    """

    def __init__(self, core, player_config: Optional[Dict[str, str]] = None):
        """
        :param core: AICore 实例（主控）
        :param player_config: dict, 可选，播放器自定义 {music: "rhythmbox", video: "mpv"}
        """
        self.core = core
        self.player_config = player_config or {"music": "rhythmbox", "video": "mpv"}

        # 企业化动作清单：name -> spec
        # spec: {func, description, permission, extra}
        self._action_specs: Dict[str, Dict[str, Any]] = {
            # 1) 系统控制（高风险：默认需要确认）
            "shutdown": {
                "func": self.shutdown,
                "description": "关机（高风险）",
                "permission": "user",
                "extra": {"risk": "high", "need_confirm": True, "tags": ["system", "power"]},
            },
            "reboot": {
                "func": self.reboot,
                "description": "重启（高风险）",
                "permission": "user",
                "extra": {"risk": "high", "need_confirm": True, "tags": ["system", "power"]},
            },
            "lock_screen": {
                "func": self.lock_screen,
                "description": "锁屏",
                "permission": "user",
                "extra": {"risk": "low", "need_confirm": False, "tags": ["system"]},
            },
            "suspend": {
                "func": self.suspend,
                "description": "休眠（高风险）",
                "permission": "user",
                "extra": {"risk": "high", "need_confirm": True, "tags": ["system", "power"]},
            },
            "logout": {
                "func": self.logout,
                "description": "注销（高风险）",
                "permission": "user",
                "extra": {"risk": "high", "need_confirm": True, "tags": ["system", "session"]},
            },
            "turn_off_display": {
                "func": self.turn_off_display,
                "description": "关闭显示器",
                "permission": "user",
                "extra": {"risk": "medium", "need_confirm": False, "tags": ["system", "display"]},
            },

            # 2) 蓝牙与音频
            "enable_bluetooth": {
                "func": self.enable_bluetooth,
                "description": "开启蓝牙",
                "permission": "user",
                "extra": {"risk": "low", "need_confirm": False, "tags": ["bluetooth"]},
            },
            "disable_bluetooth": {
                "func": self.disable_bluetooth,
                "description": "关闭蓝牙",
                "permission": "user",
                "extra": {"risk": "low", "need_confirm": False, "tags": ["bluetooth"]},
            },
            "connect_headset": {
                "func": self.connect_headset,
                "description": "连接蓝牙耳机（需提供 mac）",
                "permission": "user",
                "extra": {"risk": "medium", "need_confirm": False, "tags": ["bluetooth", "audio"]},
            },

            # 3) 多媒体/音乐
            "play_music": {
                "func": self.play_music,
                "description": "播放音乐",
                "permission": "user",
                "extra": {"risk": "low", "need_confirm": False, "tags": ["media", "music"]},
            },
            "next_song": {
                "func": self.next_song,
                "description": "下一首",
                "permission": "user",
                "extra": {"risk": "low", "need_confirm": False, "tags": ["media", "music"]},
            },
            "previous_song": {
                "func": self.previous_song,
                "description": "上一首",
                "permission": "user",
                "extra": {"risk": "low", "need_confirm": False, "tags": ["media", "music"]},
            },
            "stop_music": {
                "func": self.stop_music,
                "description": "停止播放",
                "permission": "user",
                "extra": {"risk": "low", "need_confirm": False, "tags": ["media", "music"]},
            },
            "pause_music": {
                "func": self.pause_music,
                "description": "暂停播放",
                "permission": "user",
                "extra": {"risk": "low", "need_confirm": False, "tags": ["media", "music"]},
            },
            "loop_one_on": {
                "func": self.loop_one_on,
                "description": "开启单曲循环",
                "permission": "user",
                "extra": {"risk": "low", "need_confirm": False, "tags": ["media", "music"]},
            },
            "loop_one_off": {
                "func": self.loop_one_off,
                "description": "关闭单曲循环",
                "permission": "user",
                "extra": {"risk": "low", "need_confirm": False, "tags": ["media", "music"]},
            },
            "play_video_file": {
                "func": self.play_video_file,
                "description": "播放视频文件",
                "permission": "user",
                "extra": {"risk": "medium", "need_confirm": False, "tags": ["media", "video"]},
            },
            "screenshot": {
                "func": self.screenshot,
                "description": "截图保存到指定路径",
                "permission": "user",
                "extra": {"risk": "medium", "need_confirm": False, "tags": ["system", "tools"]},
            },

            # 4) 实用/助手
            "open_browser": {
                "func": self.open_browser,
                "description": "打开浏览器",
                "permission": "user",
                "extra": {"risk": "low", "need_confirm": False, "tags": ["tools"]},
            },
            "open_url": {
                "func": self.open_url,
                "description": "打开指定 URL",
                "permission": "user",
                "extra": {"risk": "low", "need_confirm": False, "tags": ["tools"]},
            },
            "show_time": {
                "func": self.show_time,
                "description": "显示当前时间",
                "permission": "user",
                "extra": {"risk": "low", "need_confirm": False, "tags": ["tools"]},
            },
            "show_date": {
                "func": self.show_date,
                "description": "显示当前日期",
                "permission": "user",
                "extra": {"risk": "low", "need_confirm": False, "tags": ["tools"]},
            },
            "check_network": {
                "func": self.check_network,
                "description": "检查网络连通性",
                "permission": "user",
                "extra": {"risk": "low", "need_confirm": False, "tags": ["network", "tools"]},
            },
            "weather_query": {
                "func": self.weather_query,
                "description": "天气查询（示例占位）",
                "permission": "user",
                "extra": {"risk": "low", "need_confirm": False, "tags": ["tools"]},
            },
            "set_reminder": {
                "func": self.set_reminder,
                "description": "设置提醒（本地线程）",
                "permission": "user",
                "extra": {"risk": "medium", "need_confirm": False, "tags": ["tools", "scheduler"]},
            },

            # 5) 通用关闭（高风险：杀进程，建议确认）
            "close_app": {
                "func": self.close_app,
                "description": "关闭应用（pkill，高风险）",
                "permission": "user",
                "extra": {"risk": "high", "need_confirm": True, "tags": ["system", "process"]},
            },
        }

        self.register_all_actions()

    # =========================
    # 注册
    # =========================
    def register_all_actions(self) -> None:
        """
        注册所有动作到 ACTION_MANAGER
        说明：register_action 同名覆盖在插件热加载场景是可接受的（以最新实现为准）。
        """
        for name, spec in self._action_specs.items():
            if name in (
                "play_music",
                "stop_music",
                "pause_music",
                "shutdown",
                "reboot",
                "lock_screen",
                "suspend",
                "logout",
                "turn_off_display",
                "screenshot",
                "open_url",
                "open_browser",
            ):
                try:
                    meta = getattr(ACTION_MANAGER, "_actions", {}).get(name)
                    if meta and getattr(meta, "module", None) in ("music_module", "system_control"):
                        continue
                except Exception:
                    pass
            ACTION_MANAGER.register_action(
                name=name,
                func=spec["func"],
                description=spec.get("description", ""),
                permission=spec.get("permission", "user"),
                module="aicore",
                extra=spec.get("extra", {}),
            )

    # =========================
    # OS 命令执行工具（推荐用 run，避免 shell 注入）
    # =========================
    @staticmethod
    def _run(cmd: list, timeout: int = 20) -> int:
        try:
            p = subprocess.run(cmd, timeout=timeout)
            return int(p.returncode)
        except Exception:
            return 1

    # =========================
    # 1) 系统控制
    # =========================
    def shutdown(self, context=None, query=None, params=None, **kwargs):
        params = ensure_dict(params)
        return self._run(["shutdown", "now"])

    def reboot(self, context=None, query=None, params=None, **kwargs):
        params = ensure_dict(params)
        return self._run(["reboot"])

    def lock_screen(self, context=None, query=None, params=None, **kwargs):
        params = ensure_dict(params)
        return self._run(["loginctl", "lock-session"])

    def suspend(self, context=None, query=None, params=None, **kwargs):
        params = ensure_dict(params)
        return self._run(["systemctl", "suspend"])

    def logout(self, context=None, query=None, params=None, **kwargs):
        params = ensure_dict(params)
        return self._run(["gnome-session-quit", "--logout", "--no-prompt"])

    def turn_off_display(self, context=None, query=None, params=None, **kwargs):
        params = ensure_dict(params)
        # xset 依赖 X11；Wayland 下可能无效，可接受（返回码可用于提示）
        return self._run(["xset", "dpms", "force", "off"])

    # =========================
    # 2) 蓝牙与音频
    # =========================
    def enable_bluetooth(self, context=None, query=None, params=None, **kwargs):
        params = ensure_dict(params)
        return self._run(["rfkill", "unblock", "bluetooth"])

    def disable_bluetooth(self, context=None, query=None, params=None, **kwargs):
        params = ensure_dict(params)
        return self._run(["rfkill", "block", "bluetooth"])

    def connect_headset(self, context=None, query=None, params=None, mac=None, **kwargs):
        params = ensure_dict(params)
        headset_mac = mac or params.get("mac")
        if not headset_mac:
            return "未提供耳机 MAC（params.mac）"
        return self._run(["bluetoothctl", "connect", str(headset_mac)])

    # =========================
    # 3) 多媒体/音乐
    # =========================
    def play_music(self, context=None, query=None, params=None, file_path=None, **kwargs):
        params = ensure_dict(params)
        file_path = file_path or params.get("file_path")

        if hasattr(self.core, "music_manager"):
            # 你自己的音乐管理器优先
            return self.core.music_manager.play_local_music()

        player = self.player_config.get("music", "rhythmbox")
        if player == "rhythmbox":
            if file_path:
                return self._run(["rhythmbox-client", "--play-uri", f"file://{file_path}"])
            return self._run(["rhythmbox-client", "--play"])
        if player == "playerctl":
            return self._run(["playerctl", "play"])

        # 自定义播放器：尽量不走 shell
        if file_path:
            try:
                subprocess.Popen([player, file_path])
                return 0
            except Exception:
                return 1
        try:
            subprocess.Popen([player])
            return 0
        except Exception:
            return 1

    def next_song(self, context=None, query=None, params=None, **kwargs):
        params = ensure_dict(params)
        player = self.player_config.get("music", "rhythmbox")
        if player == "rhythmbox":
            return self._run(["rhythmbox-client", "--next"])
        if player == "playerctl":
            return self._run(["playerctl", "next"])
        return 0

    def previous_song(self, context=None, query=None, params=None, **kwargs):
        params = ensure_dict(params)
        player = self.player_config.get("music", "rhythmbox")
        if player == "rhythmbox":
            return self._run(["rhythmbox-client", "--previous"])
        if player == "playerctl":
            return self._run(["playerctl", "previous"])
        return 0

    def stop_music(self, context=None, query=None, params=None, **kwargs):
        params = ensure_dict(params)
        player = self.player_config.get("music", "rhythmbox")
        if player == "rhythmbox":
            return self._run(["rhythmbox-client", "--stop"])
        if player == "playerctl":
            return self._run(["playerctl", "stop"])
        return 0

    def pause_music(self, context=None, query=None, params=None, **kwargs):
        params = ensure_dict(params)
        player = self.player_config.get("music", "rhythmbox")
        if player == "rhythmbox":
            return self._run(["rhythmbox-client", "--pause"])
        if player == "playerctl":
            return self._run(["playerctl", "pause"])
        return 0

    def loop_one_on(self, context=None, query=None, params=None, **kwargs):
        params = ensure_dict(params)
        if hasattr(self.core, "music_manager"):
            self.core.music_manager.set_loop_mode("one")
            return "已开启单曲循环"
        return "暂不支持（未发现 music_manager）"

    def loop_one_off(self, context=None, query=None, params=None, **kwargs):
        params = ensure_dict(params)
        if hasattr(self.core, "music_manager"):
            self.core.music_manager.set_loop_mode("off")
            return "已关闭单曲循环"
        return "暂不支持（未发现 music_manager）"

    def play_video_file(self, context=None, query=None, params=None, filepath=None, **kwargs):
        params = ensure_dict(params)
        player = self.player_config.get("video", "mpv")
        path = filepath or params.get("filepath") or os.path.expanduser("~/视频/指定文件名.mp4")
        try:
            if player == "mpv":
                subprocess.Popen(["mpv", path])
            elif player == "vlc":
                subprocess.Popen(["vlc", path])
            else:
                subprocess.Popen([player, path])
            return {"ok": True, "player": player, "path": path}
        except Exception as e:
            return {"ok": False, "error": str(e), "player": player, "path": path}

    def screenshot(self, context=None, query=None, params=None, save_path=None, **kwargs):
        params = ensure_dict(params)
        path = save_path or params.get("save_path") or os.path.expanduser("~/图片/截图.png")
        return self._run(["gnome-screenshot", "-f", path])

    # =========================
    # 4) 日常助手/工具
    # =========================
    def open_browser(self, context=None, query=None, params=None, **kwargs):
        params = ensure_dict(params)
        return webbrowser.open("https://www.bing.com")

    def open_url(self, context=None, query=None, params=None, url=None, **kwargs):
        params = ensure_dict(params)
        return webbrowser.open(url or params.get("url") or "https://www.bing.com")

    def show_time(self, context=None, query=None, params=None, **kwargs):
        params = ensure_dict(params)
        return f"当前时间：{datetime.datetime.now().strftime('%H:%M:%S')}"

    def show_date(self, context=None, query=None, params=None, **kwargs):
        params = ensure_dict(params)
        return f"今天日期：{datetime.date.today().strftime('%Y-%m-%d')}"

    def check_network(self, context=None, query=None, params=None, **kwargs):
        params = ensure_dict(params)
        # 小改：不用 shell 重定向；直接丢弃输出
        try:
            p = subprocess.run(["ping", "-c", "1", "baidu.com"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return "网络畅通" if p.returncode == 0 else "网络不可用"
        except Exception:
            return "网络不可用"

    def weather_query(self, context=None, query=None, params=None, city=None, **kwargs):
        params = ensure_dict(params)
        city = city or params.get("city") or "北京"
        return f"【示例】城市：{city}，当前天气晴，温度25°C。"

    def set_reminder(self, context=None, query=None, params=None, minutes=1, message=None, **kwargs):
        params = ensure_dict(params)
        minutes = int(params.get("minutes", minutes) or 1)
        message = message or params.get("message", "提醒您")

        def remind():
            time.sleep(max(1, minutes) * 60)
            print(f"⏰ 时间到：{message}")

        threading.Thread(target=remind, daemon=True).start()
        return f"已设置 {minutes} 分钟后提醒"

    # =========================
    # 5) 通用关闭（pkill 高风险）
    # =========================
    def close_app(self, context=None, query=None, params=None, app_name=None, **kwargs):
        params = ensure_dict(params)
        app = app_name or params.get("app_name") or (query or "").strip().lower()
        if not app:
            return "未指定要关闭的应用"

        app_map = {
            "浏览器": "chrome",
            "chrome": "chrome",
            "firefox": "firefox",
            "mpv": "mpv",
            "vlc": "vlc",
            "rhythmbox": "rhythmbox",
            "终端": "gnome-terminal",
            "edge": "microsoft-edge",
        }
        proc = app_map.get(app, app)

        # 关键：避免 shell 注入，改用 subprocess
        try:
            p = subprocess.run(["pkill", "-f", str(proc)])
            return f"已尝试关闭应用：{app}（code={p.returncode}）"
        except Exception as e:
            return f"关闭应用失败: {e}"
