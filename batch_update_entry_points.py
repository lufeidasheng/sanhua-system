import os
import json
import shutil

MODULES_DIR = "./modules"
BACKUP_SUFFIX = ".bak"

# 根据目录名自动判断支持的入口点
def determine_entry_points(module_name: str):
    name = module_name.lower()
    voice_keys = ["voice", "wake_word", "stt", "speech", "audio", "capture", "consumer"]
    gui_keys = ["gui", "widget", "chat", "input", "menu", "overlay"]
    cli_keys = ["code", "format", "executor", "inserter", "reader", "reviewer", "system", "monitor", "manager", "logbook", "model", "music", "self_learning", "test", "hello", "language_bridge"]

    entry_points = set()

    if any(k in name for k in voice_keys):
        entry_points.add("voice")
    if any(k in name for k in gui_keys):
        entry_points.add("gui")
    if any(k in name for k in cli_keys):
        entry_points.add("cli")

    # 如果没有匹配任何，默认给 cli
    if not entry_points:
        entry_points.add("cli")

    return sorted(entry_points)

def backup_manifest(manifest_path):
    backup_path = manifest_path + BACKUP_SUFFIX
    if not os.path.exists(backup_path):
        shutil.copyfile(manifest_path, backup_path)
        print(f"备份 {manifest_path} 到 {backup_path}")

def update_manifest(module_path, module_name):
    manifest_path = os.path.join(module_path, "manifest.json")
    if not os.path.isfile(manifest_path):
        print(f"跳过 {module_name}，无manifest.json")
        return
    try:
        backup_manifest(manifest_path)
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        current_eps = set(data.get("entry_points", []))
        auto_eps = set(determine_entry_points(module_name))
        new_eps = sorted(current_eps.union(auto_eps))
        data["entry_points"] = new_eps
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"{module_name} 更新入口点: {new_eps}")
    except Exception as e:
        print(f"{module_name} 处理失败: {e}")

def main():
    for module_name in os.listdir(MODULES_DIR):
        module_path = os.path.join(MODULES_DIR, module_name)
        if not os.path.isdir(module_path):
            continue
        update_manifest(module_path, module_name)

if __name__ == "__main__":
    main()
