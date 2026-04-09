"""
三花聚顶 · music_module 音乐播放模块（全局标准/热插拔版）🎶
支持自动扫描本地音乐、后台播放、模块级单例、全局动作注册。
作者：三花聚顶开发团队
"""

import os
import random
import threading
import subprocess
import time

from core.core2_0.sanhuatongyu.module.base import BaseModule
from core.core2_0.sanhuatongyu.logger import get_logger
from core.core2_0.sanhuatongyu.action_dispatcher import dispatcher as ACTION_DISPATCHER

# ============ 日志器 =============
logger = get_logger("music_module")

# ============ 内存引擎（自适应） =============
try:
    from core.aicore.memory import memory_engine
except ImportError as e:
    logger.warning(f"导入 memory_engine 失败: {e}")
    class FallbackMemory:
        def recall(self, key, default=None):
            return default
        def remember(self, key, value):
            pass
    memory_engine = FallbackMemory()

IS_FEDORA = os.path.exists('/etc/fedora-release')

class MusicManager(BaseModule):
    """
    三花聚顶 · 音乐播放管理器（模块单例、全局action、热插拔事件）
    """
    def __init__(self, meta=None, context=None):
        super().__init__(meta, context)
        self._cached_songs = []
        self._last_scan = 0
        self._player_name = self._detect_best_player()
        self.config = (meta or {}).get("config", {}) if meta else {}
        logger.info("🎵 MusicManager初始化，播放器=%s", self._player_name)

    def preload(self):
        logger.info("🎵 MusicManager preload开始")
        self._register_actions()
        logger.info("🎵 MusicManager preload结束")

    def setup(self):
        logger.info("🎵 MusicManager setup开始")
        self._register_actions()
        if hasattr(self.context, "event_bus") and self.context.event_bus:
            self.context.event_bus.subscribe("music.play", self.handle_event)
        logger.info("🎵 MusicManager setup结束")

    def start(self):
        logger.info("🎵 MusicManager启动完成")

    def stop(self):
        logger.info("🎵 MusicManager已停止")

    def handle_event(self, event_name, data=None):
        if event_name == "music.play":
            logger.info(f"🎶 收到 music.play 事件: {data}")
            return self.play_music_action()
        return None

    def play_music_action(self, context=None, params=None, **kwargs):
        """
        对外全局调用接口（兼容action/event/直接方法）
        """
        return self.play_local_music()

    def play_local_music(self) -> str:
        """随机选择一首本地音乐并后台播放"""
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
        threading.Thread(
            target=self._play_music_file,
            args=(song,),
            daemon=True,
            name="MusicPlayer"
        ).start()
        logger.info(f"🎶 正在播放: {song}")
        return f"🎶 正在播放: {os.path.basename(song)}"

    def _detect_best_player(self):
        players = ['mpv', 'mplayer', 'ffplay', 'vlc']
        if IS_FEDORA:
            players.insert(0, 'mpv')
        for player in players:
            if self._is_player_available(player):
                return player
        return None

    def _is_player_available(self, player_name):
        try:
            subprocess.run(
                [player_name, '--version'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True
            )
            return True
        except Exception:
            return False

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
            fedora_params = ["--no-terminal", "--really-quiet"] if IS_FEDORA else []
            volume = memory_engine.recall("music_volume")
            if volume and isinstance(volume, (int, float)):
                if self._player_name == 'mpv':
                    fedora_params.append(f"--volume={volume}")
                elif self._player_name == 'mplayer':
                    fedora_params.append(f"-volume {volume}")
            if not os.path.exists(filepath):
                logger.error(f"🎵 音乐文件不存在: {filepath}")
                return
            subprocess.Popen(
                [self._player_name, filepath] + fedora_params,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
        except Exception as e:
            logger.error(f"🎵 音乐播放失败: {e}")

    def cleanup(self):
        ACTION_DISPATCHER.unregister_action("music.play")
        logger.info("🎵 music.play 动作反注册完成")

    def _register_actions(self):
        # 避免重复注册
        if "music.play" not in [a["name"] for a in ACTION_DISPATCHER.list_actions(detailed=True)]:
            ACTION_DISPATCHER.register_action(
                name="music.play",
                func=self.play_music_action,
                description="随机播放本地音乐（Fedora优化）",
                permission="user",
                module="music_module"
            )
            logger.info("🎶 注册标准动作: music.play")
        else:
            logger.info("🎶 music.play 已注册，跳过")

# ==== 热插拔/脚手架注册辅助 ====
def register_actions(dispatcher, context=None):
    mod = MusicManager(meta=dispatcher.get_module_meta("music_module"), context=context)
    dispatcher.register_action("music.play", mod.play_music_action, module="music_module")
    logger.info("register_actions: music.play 注册完成")
