import pyaudio

p = pyaudio.PyAudio()
print("可用的音频设备：")
for i in range(p.get_device_count()):
    dev = p.get_device_info_by_index(i)
    print(f"{i}: {dev['name']}")

