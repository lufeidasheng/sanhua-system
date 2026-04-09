import logging
import threading
import time
import wave
import pyaudio
import os

from core.core2_0.event_bus import subscribe, emit

log = logging.getLogger(__name__)

# === 录音配置 ===
AUDIO_RATE = 16000
AUDIO_CHANNELS = 1
AUDIO_FORMAT = pyaudio.paInt16
CHUNK = 1024
RECORD_SECONDS = 5
SAVE_PATH = os.path.abspath("temp.wav")


def register_actions():
    """
    注册事件监听函数
    """
    subscribe("wake_word.detected", on_wake_word_detected)
    log.info(f"🔔 voice_entry 模块已监听唤醒事件 wake_word.detected")


def on_wake_word_detected():
    """
    收到唤醒词触发后，启动录音流程
    """
    log.info("🎤 收到唤醒词唤醒，开始录音...")
    threading.Thread(target=record_and_emit, daemon=True).start()


def record_and_emit():
    """
    录音并发送 voice_input.recorded 事件
    """
    audio = pyaudio.PyAudio()
    stream = audio.open(format=AUDIO_FORMAT,
                        channels=AUDIO_CHANNELS,
                        rate=AUDIO_RATE,
                        input=True,
                        frames_per_buffer=CHUNK)

    frames = []
    log.debug("🎙️ 正在录音中...")
    for _ in range(0, int(AUDIO_RATE / CHUNK * RECORD_SECONDS)):
        data = stream.read(CHUNK)
        frames.append(data)

    stream.stop_stream()
    stream.close()
    audio.terminate()

    wf = wave.open(SAVE_PATH, 'wb')
    wf.setnchannels(AUDIO_CHANNELS)
    wf.setsampwidth(audio.get_sample_size(AUDIO_FORMAT))
    wf.setframerate(AUDIO_RATE)
    wf.writeframes(b''.join(frames))
    wf.close()

    log.info(f"✅ 录音完成，保存为 {SAVE_PATH}")
    emit("voice_input.recorded", filepath=SAVE_PATH)


def entry():
    """
    voice_entry 模块入口函数
    """
    log.info(f"✨ [{__name__}] 入口函数已调用，voice_entry 模块启动中...")
