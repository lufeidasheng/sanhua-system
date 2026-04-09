import pyttsx3

engine = pyttsx3.init()
voices = engine.getProperty('voices')
# 自动选取中文（适配 espeak-ng，兼容 Windows/Mac）
zh_voice = None
for v in voices:
    if 'zh' in v.id.lower() or 'chinese' in v.name.lower():
        zh_voice = v.id
        print(f"发现中文语音: {v.id} - {v.name}")
        break
if zh_voice:
    engine.setProperty('voice', zh_voice)
    print(f"已设置语音为: {zh_voice}")
else:
    print("⚠️ 未找到中文语音，尝试使用默认语音")

engine.setProperty('rate', 100)   # 语速
engine.setProperty('volume', 1.0) # 音量

engine.say("你好，欢迎来到三花聚顶系统。Hello, welcome to Sanhua Juding.")
engine.runAndWait()
print("✅ 测试完成")
