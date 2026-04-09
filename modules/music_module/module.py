"""
三花聚顶 · music_module 音乐播放模块（全局标准/热插拔旗舰版）🎶
支持自动扫描本地音乐、后台播放、模块级单例、全局动作注册、健康检测与事件驱动。
作者：三花聚顶开发团队
"""

import os
import random
import threading
import subprocess
import time
import shutil
import sys

from core.core2_0.sanhuatongyu.module.base import BaseModule
from core.core2_0.sanhuatongyu.logger import get_logger
from core.core2_0.sanhuatongyu.action_dispatcher import dispatcher as ACTION_DISPATCHER

logger = get_logger("music_module")

# ============ 内存引擎（自适应/降级） ===========
try:
    from core.aicore.memory import memory_engine
except ImportError as e:
    logger.warning(f"导入 memory_engine 失败: {e}")
    class FallbackMemory:
        def recall(self, key, default=None): return default
        def remember(self, key, value): pass
    memory_engine = FallbackMemory()

IS_FEDORA = os.path.exists('/etc/fedora-release')

class MusicManager(BaseModule):
    """
    三花聚顶 · 音乐播放管理器（全局动作/事件/健康/模块热插拔单例）
    """
    def __init__(self, meta=None, context=None):
        super().__init__(meta, context)
        # 标准化元数据属性读取
        self.config = getattr(meta, "config", {}) if meta else {}
        self._cached_songs = []
        self._last_scan = 0
        self._player_name, self._backend_reason, self._backend_candidates = self._select_backend()
        self._active_backend = None
        self._active_track = None
        self._active_process = None
        logger.info(
            f"🎵 MusicManager 初始化完成，后端={self._player_name}，原因={self._backend_reason}"
        )

    def preload(self):
        logger.info("🎵 MusicManager preload 开始")
        self._register_actions()
        logger.info("🎵 MusicManager preload 结束")

    def setup(self):
        logger.info("🎵 MusicManager setup 开始")
        self._register_actions()
        if hasattr(self.context, "event_bus") and self.context.event_bus:
            self.context.event_bus.subscribe("music.play", self.handle_event)
        logger.info("🎵 MusicManager setup 结束")

    def start(self):
        logger.info("🎵 MusicManager 启动完成")

    def stop(self):
        logger.info("🎵 MusicManager 已停止")

    def health_check(self):
        """标准健康状态上报"""
        if self._player_name:
            return {
                "status": "OK",
                "backend": self._player_name,
                "backend_candidates": self._backend_candidates,
                "backend_reason": self._backend_reason,
                "player": self._player_name,
                "music_count": len(self._cached_songs),
                "last_scan": self._last_scan
            }
        return {
            "status": "DEGRADED",
            "reason": "player_missing",
            "backend": None,
            "backend_candidates": self._backend_candidates,
            "backend_reason": self._backend_reason,
            "player": self._player_name,
            "music_count": len(self._cached_songs),
            "last_scan": self._last_scan
        }

    def handle_event(self, event_name, data=None):
        if event_name == "music.play":
            logger.info(f"🎶 收到 music.play 事件: {data}")
            return self.play_music_action()
        return None

    def play_music_action(self, context=None, params=None, **kwargs):
        """
        全局标准调用接口（action/event/方法三通道）
        """
        params = params or {}
        filepath = params.get("filepath") or params.get("path") or params.get("file")
        if filepath:
            logger.info(f"🎶 play_music 指定文件播放: {filepath}")
            if not os.path.exists(filepath):
                return f"❌ 音乐文件不存在: {filepath}"
            self._play_music_file(filepath)
            return f"🎶 正在播放: {os.path.basename(filepath)}"
        if sys.platform == "darwin":
            ok, msg = self._play_native_music_app()
            if ok:
                self._active_backend = "music_app"
                self._active_track = None
                self._active_process = None
                return msg
            fallback = self.play_local_music()
            return f"{msg}；已回退到本地播放：{fallback}"
        return self.play_local_music()

    def pause_music_action(self, context=None, params=None, **kwargs) -> str:
        if self._active_backend == "music_app" and sys.platform == "darwin":
            ok, msg = self._pause_native_music_app()
            if ok:
                self._active_backend = None
                self._active_track = None
                self._active_process = None
            return msg
        if self._active_backend == "local_file":
            ok, msg = self._stop_local_playback()
            return msg
        return "pause_music not implemented on this platform"

    def stop_music_action(self, context=None, params=None, **kwargs) -> str:
        if self._active_backend == "music_app" and sys.platform == "darwin":
            ok, msg = self._pause_native_music_app()
            if ok:
                self._active_backend = None
                self._active_track = None
                self._active_process = None
            return msg
        if self._active_backend == "local_file":
            ok, msg = self._stop_local_playback()
            return msg
        return "stop_music not implemented on this platform"

    def play_local_music(self) -> str:
        """🌸 随机选择一首本地音乐后台播放"""
        if not self._player_name:
            logger.warning("❌ 未找到可用播放器")
            return "❌ 未找到可用音频播放器，请安装 mpv 或 mplayer"

        now = time.time()
        if not self._cached_songs or now - self._last_scan > 1800:
            self._cached_songs = self._scan_music()
            self._last_scan = now

        if not self._cached_songs:
            logger.info("🎵 没有扫描到音乐文件")
            return "🎵 未找到音乐文件"

        song = random.choice(self._cached_songs)
        self._active_backend = "local_file"
        self._active_track = song
        threading.Thread(
            target=self._play_music_file,
            args=(song,),
            daemon=True,
            name="MusicPlayer"
        ).start()
        logger.info(f"🎶 正在播放: {song}")
        return f"🎶 正在播放: {os.path.basename(song)}"

    def _select_backend(self):
        candidates, default_reason = self._get_backend_candidates()
        for backend in candidates:
            if self._is_backend_available(backend):
                reason = self._backend_reason_for(backend, default_reason)
                return backend, reason, candidates
        return None, "no_backend_available", candidates

    def _get_backend_candidates(self):
        if sys.platform == "darwin":
            return (
                ["native_music_app", "afplay", "mpv", "vlc", "ffplay", "mplayer"],
                "preferred_for_darwin",
            )
        players = ["mpv", "mplayer", "ffplay", "vlc"]
        if IS_FEDORA:
            players.insert(0, "mpv")
        return players, "preferred_for_linux"

    def _backend_reason_for(self, backend, default_reason):
        if backend == "native_music_app":
            return "preferred_for_darwin"
        return "local_player_available" if backend else default_reason

    def _is_backend_available(self, backend):
        if backend == "native_music_app":
            return False
        return shutil.which(backend) is not None

    def _scan_music(self):
        # 优先用用户记忆/自定义目录
        default_dir = os.path.expanduser("~/音乐") if IS_FEDORA else os.path.expanduser("~/Music")
        music_dir = memory_engine.recall("music_dir") or default_dir
        if not os.path.exists(music_dir):
            logger.warning(f"🎵 音乐目录不存在: {music_dir}")
            return []
        audio_exts = [".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus"]
        songs = []
        try:
            for root, _, files in os.walk(music_dir):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in audio_exts):
                        songs.append(os.path.join(root, file))
            logger.info(f"🎵 扫描到 {len(songs)} 首音乐")
        except Exception as e:
            logger.error(f"🎵 扫描音乐目录异常: {e}")
        return songs

    def _play_music_file(self, filepath: str):
        if not self._player_name:
            return
        try:
            if not os.path.exists(filepath):
                logger.error(f"🎵 音乐文件不存在: {filepath}")
                return
            if self._player_name == "afplay":
                cmd = [self._player_name, filepath]
            else:
                fedora_params = ["--no-terminal", "--really-quiet"] if IS_FEDORA else []
                volume = memory_engine.recall("music_volume")
                if volume and isinstance(volume, (int, float)):
                    if self._player_name == 'mpv':
                        fedora_params.append(f"--volume={volume}")
                    elif self._player_name == 'mplayer':
                        fedora_params.append(f"-volume {volume}")
                cmd = [self._player_name, filepath] + fedora_params
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            self._active_backend = "local_file"
            self._active_track = filepath
            self._active_process = proc
        except Exception as e:
            logger.error(f"🎵 音乐播放失败: {e}")

    def _play_native_music_app(self) -> tuple[bool, str]:
        try:
            script = (
                "tell application \"Music\"\n"
                "activate\n"
                "play\n"
                "set s to player state as string\n"
                "return s\n"
                "end tell\n"
            )
            proc = subprocess.run(
                ["osascript", "-e", script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
            state = (proc.stdout or "").strip().lower()
            if state == "playing":
                return True, "🎵 Music.app 正在播放"
            return False, f"🎵 Music.app 未进入播放态（state={state or 'unknown'}）"
        except Exception as e:
            logger.warning(f"🎵 Music.app 播放失败，回退本地播放: {e}")
            return False, f"🎵 Music.app 播放失败：{e}"

    def _pause_native_music_app(self) -> tuple[bool, str]:
        try:
            script = (
                "tell application \"Music\"\n"
                "pause\n"
                "set s to player state as string\n"
                "return s\n"
                "end tell\n"
            )
            proc = subprocess.run(
                ["osascript", "-e", script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
            state = (proc.stdout or "").strip().lower()
            if state != "playing":
                return True, "⏸️ Music.app 已暂停"
            return False, f"⚠️ Music.app 未能暂停（state={state or 'unknown'}）"
        except Exception as e:
            logger.warning(f"🎵 Music.app 暂停失败: {e}")
            return False, f"⚠️ Music.app 暂停失败：{e}"

    def _stop_local_playback(self) -> tuple[bool, str]:
        proc = self._active_process
        if not proc:
            return False, "⚠️ 当前没有可停止的本地播放进程"
        try:
            proc.poll()
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
            self._active_process = None
            self._active_backend = None
            self._active_track = None
            return True, "⏹️ 已停止本地播放"
        except Exception as e:
            logger.warning(f"🎵 本地播放停止失败: {e}")
            return False, f"⚠️ 本地播放停止失败：{e}"

    def cleanup(self):
        ACTION_DISPATCHER.unregister_action("music.play")
        logger.info("🎵 music.play 动作反注册完成")

    def _register_actions(self):
        # 优先绑定到当前运行时 dispatcher（GUI live runtime 对齐）
        disp = getattr(self.context, "action_dispatcher", None) or ACTION_DISPATCHER
        try:
            self_id = id(disp)
            fallback_id = id(ACTION_DISPATCHER)
            logger.info(f"🎶 play_music dispatcher id={self_id} fallback_id={fallback_id}")
            meta_before = getattr(getattr(disp, "_actions", {}), "get", lambda *_: None)("play_music")
            before_mod = getattr(meta_before, "module", None)
            before_func = getattr(meta_before, "func", None)
            before_qname = getattr(before_func, "__qualname__", None) or getattr(before_func, "__name__", None)
            logger.info(f"🎶 play_music before: module={before_mod} func={before_qname}")
        except Exception as _e:
            logger.info(f"🎶 play_music before: meta_probe_error={_e}")

        # 避免重复注册；若同名动作来源非 music_module，则覆盖
        existing = None
        for a in disp.list_actions(detailed=True):
            if a.get("name") == "play_music":
                existing = a
                break
        if existing and existing.get("module") != "music_module":
            logger.info(f"🎶 play_music 已被 {existing.get('module') or 'unknown'} 注册，改为 music_module 覆盖")
        if (not existing) or (existing.get("module") != "music_module"):
            disp.register_action(
                name="play_music",
                func=self.play_music_action,
                description="随机播放本地音乐（Fedora优化）",
                permission="user",
                module="music_module"
            )
            logger.info("🎶 注册标准动作: play_music")
        else:
            logger.info("🎶 play_music 已注册（music_module），跳过")

        disp.register_action(
            name="stop_music",
            func=self.stop_music_action,
            description="暂停音乐播放（Music.app）",
            permission="user",
            module="music_module",
        )
        logger.info("🎶 注册标准动作: stop_music")

        disp.register_action(
            name="pause_music",
            func=self.pause_music_action,
            description="暂停音乐播放（Music.app）",
            permission="user",
            module="music_module",
        )
        logger.info("🎶 注册标准动作: pause_music")

        try:
            meta_after = getattr(getattr(disp, "_actions", {}), "get", lambda *_: None)("play_music")
            after_mod = getattr(meta_after, "module", None)
            after_func = getattr(meta_after, "func", None)
            after_qname = getattr(after_func, "__qualname__", None) or getattr(after_func, "__name__", None)
            logger.info(f"🎶 play_music after: module={after_mod} func={after_qname}")
        except Exception as _e:
            logger.info(f"🎶 play_music after: meta_probe_error={_e}")

# ==== 热插拔/脚手架注册辅助 ====
def register_actions(dispatcher, context=None):
    meta = dispatcher.get_module_meta("music_module") if hasattr(dispatcher, "get_module_meta") else None
    mod = MusicManager(meta=meta, context=context)
    dispatcher.register_action("play_music", mod.play_music_action, module="music_module")
    dispatcher.register_action("stop_music", mod.stop_music_action, module="music_module")
    dispatcher.register_action("pause_music", mod.pause_music_action, module="music_module")
    logger.info("register_actions: play_music 注册完成")

# ==== 标准模块元数据 ====
MODULE_METADATA = {
    "name": "music_module",
    "version": "1.0.0",
    "description": "本地音乐管理与随机播放模块，支持后台独立播放和Fedora优化",
    "author": "三花聚顶开发团队",
    "entry": "modules.music_module",
    "actions": [
        {
            "name": "play_music",
            "description": "随机播放本地音乐文件",
            "permission": "user"
        }
    ],
    "dependencies": [],
    "config_schema": {
        "music_dir": {
            "type": "string",
            "default": "",
            "description": "自定义音乐目录（如未设置则自动检测）"
        }
    }
}
