import os
import threading
import asyncio
import tempfile
import subprocess

class VoiceQueue:
    """聚核助手语音播放队列（非阻塞 + 顺序 + 清理）"""
    def __init__(self):
        self.queue = []
        self.lock = threading.Lock()
        self.is_playing = False
        self.stop_requested = False

    def add(self, text):
        with self.lock:
            self.queue.append(text)
            if not self.is_playing and not self.stop_requested:
                self._play_next()

    def _play_next(self):
        if self.stop_requested:
            return

        with self.lock:
            if not self.queue:
                self.is_playing = False
                return
            text = self.queue.pop(0)
            self.is_playing = True

        threading.Thread(target=self._play, args=(text,), daemon=True).start()

    def _play(self, text):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmpfile:
                file_path = tmpfile.name

            async def generate():
                try:
                    import edge_tts
                    tts = edge_tts.Communicate(text, voice="zh-CN-XiaoxiaoNeural")
                    await tts.save(file_path)
                except ImportError:
                    print("[聚核助手] 缺少 edge_tts")
                    return False
                return True

            if not loop.run_until_complete(generate()):
                return

            try:
                process = subprocess.Popen(
                    ["mpv", file_path, "--no-terminal", "--really-quiet"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                process.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                print("[聚核助手] mpv 播放超时")
                process.kill()
            except FileNotFoundError:
                print("[聚核助手] mpv 未安装")
        except Exception as e:
            print(f"[聚核助手] 播放失败: {e}")
        finally:
            try:
                os.unlink(file_path)
            except:
                pass

            with self.lock:
                self.is_playing = False
                if self.queue and not self.stop_requested:
                    self._play_next()

    def clear(self):
        with self.lock:
            self.queue.clear()
            self.stop_requested = True
