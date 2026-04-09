import os
import shutil
import json

MOD_DIR = "modules"

# 确保模块目录存在
if not os.path.exists(MOD_DIR):
    os.makedirs(MOD_DIR)
    print(f"📁 创建模块目录: {MOD_DIR}")

print("🚀 开始模块标准化过程...")

# 处理所有.py模块文件
for fname in os.listdir(MOD_DIR):
    # 跳过非Python文件和特殊文件
    if not fname.endswith(".py") or fname.startswith("__"):
        continue
    
    mod_name = fname[:-3]  # 去掉.py扩展名
    src = os.path.join(MOD_DIR, fname)
    dest_dir = os.path.join(MOD_DIR, mod_name)
    dest = os.path.join(dest_dir, fname)
    
    print(f"🛠️  正在处理模块: {mod_name}")
    
    # 创建模块目录
    os.makedirs(dest_dir, exist_ok=True)
    
    # 移动文件到新目录
    if os.path.exists(src):
        shutil.move(src, dest)
        print(f"📄 移动文件: {fname} → {dest}")
    else:
        print(f"⚠️  文件不存在: {src}")
        continue
    
    # 创建manifest.json配置文件
    manifest = {
        "id": mod_name,
        "name": mod_name.replace("_", " ").title(),
        "entry_file": fname,
        "version": "1.0.0",
        "description": f"{mod_name.replace('_', ' ').title()} 功能模块",
        "author": "系统自动生成",
        "created_at": "2025-07-12",
        "dependencies": []
    }
    
    manifest_path = os.path.join(dest_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=4)
    
    print(f"⚙️  创建配置文件: {manifest_path}")
    print(f"✅ 模块 {mod_name} 标准化完成\n")

print("🎉 所有模块已标准化")
