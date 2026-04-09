import speech_recognition as sr
import pyaudio

# 列出所有麦克风设备
print("可用麦克风设备:")
p = pyaudio.PyAudio()
for i in range(p.get_device_count()):
    dev = p.get_device_info_by_index(i)
    if dev['maxInputChannels'] > 0:
        print(f"{i}: {dev['name']}")

# 测试录音
r = sr.Recognizer()
with sr.Microphone() as source:
    print("\n请说话（5秒）...")
    audio = r.listen(source, timeout=5)
    print("录音完成!")
    
try:
    print("识别结果:", r.recognize_google(audio, language='zh-CN'))
except sr.UnknownValueError:
    print("无法识别音频")
except sr.RequestError as e:
    print(f"请求错误: {e}")
