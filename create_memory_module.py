import os
import json

base_path = 'aicore/memory'
os.makedirs(base_path, exist_ok=True)

# 1. __init__.py
with open(os.path.join(base_path, '__init__.py'), 'w', encoding='utf-8') as f:
    f.write('# Memory module init\n')

# 2. memory_engine.py
memory_engine_code = '''
import json
import os
from datetime import datetime

MEMORY_FILE = os.path.join(os.path.dirname(__file__), 'memory.json')

def load_memory():
    if not os.path.exists(MEMORY_FILE):
        return {}
    with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_memory(data):
    with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def remember(key, value):
    memory = load_memory()
    memory[key] = value
    save_memory(memory)

def recall(key):
    memory = load_memory()
    return memory.get(key, None)

def forget(key):
    memory = load_memory()
    if key in memory:
        del memory[key]
        save_memory(memory)

def log_event(description):
    memory = load_memory()
    history = memory.get("history", [])
    history.append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event": description
    })
    memory["history"] = history
    save_memory(memory)
'''.strip()

with open(os.path.join(base_path, 'memory_engine.py'), 'w', encoding='utf-8') as f:
    f.write(memory_engine_code)

# 3. memory.json（默认记忆内容）
default_memory = {
    "user_name": "你",
    "preferences": {
        "language": "zh-CN",
        "tone": "温和、亲切",
        "favorite_style": "古风",
        "likes": ["美女形象", "虚拟助手", "干净的UI"]
    },
    "habits": {
        "wake_up_time": "08:30",
        "daily_tasks": ["提醒喝水", "查天气"]
    },
    "history": [
        {
            "date": "2025-06-16 09:00:00",
            "event": "设置助手为女性，风格为温柔虚拟形象"
        }
    ]
}

with open(os.path.join(base_path, 'memory.json'), 'w', encoding='utf-8') as f:
    json.dump(default_memory, f, ensure_ascii=False, indent=2)

print("✅ 记忆模块文件创建完成：aicore/memory/")
