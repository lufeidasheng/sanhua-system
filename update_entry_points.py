import os
import json
import re

def find_manifest_file(module_path):
    """在模块目录中查找manifest.json文件（优先检查版本子目录）"""
    # 检查是否有版本子目录（如'1/'）
    version_dirs = [d for d in os.listdir(module_path) 
                  if os.path.isdir(os.path.join(module_path, d)) and d.isdigit()]
    
    # 优先使用最新版本目录中的manifest
    if version_dirs:
        # 按版本号排序（降序）
        version_dirs.sort(key=int, reverse=True)
        latest_version = version_dirs[0]
        version_path = os.path.join(module_path, latest_version)
        version_manifest = os.path.join(version_path, "manifest.json")
        
        if os.path.exists(version_manifest):
            return version_manifest
    
    # 回退到模块根目录的manifest
    root_manifest = os.path.join(module_path, "manifest.json")
    return root_manifest if os.path.exists(root_manifest) else None

def update_module_entry_points(modules_dir):
    updated_count = 0
    skipped_modules = []
    error_modules = []
    
    print(f"扫描目录: {modules_dir}")
    module_list = [d for d in os.listdir(modules_dir) 
                  if os.path.isdir(os.path.join(modules_dir, d)) and d != "__pycache__"]
    
    print(f"找到 {len(module_list)} 个模块")
    
    for module_name in module_list:
        module_path = os.path.join(modules_dir, module_name)
        manifest_path = find_manifest_file(module_path)
        
        if not manifest_path:
            skipped_modules.append(f"{module_name} (未找到manifest文件)")
            continue
            
        try:
            # 检查文件大小（处理空文件）
            if os.path.getsize(manifest_path) == 0:
                error_modules.append(f"{module_name} (manifest文件为空)")
                continue
                
            with open(manifest_path, 'r', encoding='utf-8') as f:
                try:
                    manifest = json.load(f)
                except json.JSONDecodeError as e:
                    error_modules.append(f"{module_name} (JSON解析错误: {str(e)})")
                    continue
            
            # 确保entry_point字段存在
            if "entry_point" not in manifest:
                # 尝试从目录结构推断默认入口点
                possible_entry = f"{module_name}.py:main"
                print(f"警告: {module_name} 缺少entry_point字段，将添加默认值: {possible_entry}")
                manifest["entry_point"] = possible_entry
                updated = True
            else:
                # 更新现有entry_point
                old_entry = manifest["entry_point"]
                if ':' not in old_entry:
                    # 修复缺少冒号分隔符的格式
                    manifest["entry_point"] = f"{old_entry}:main"
                    updated = True
                elif not old_entry.startswith(module_name + '.'):
                    # 添加模块名前缀
                    file_part, func_part = old_entry.split(':', 1)
                    new_entry = f"{module_name}.{file_part}:{func_part}"
                    manifest["entry_point"] = new_entry
                    updated = True
                else:
                    # 无需更新
                    skipped_modules.append(f"{module_name} (entry_point已是最新格式)")
                    continue
            
            # 保存更新后的manifest
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=4, ensure_ascii=False)
                f.write('\n')
            
            updated_count += 1
            print(f"已更新 {module_name}")
            
        except Exception as e:
            error_modules.append(f"{module_name} (错误: {str(e)})")
    
    # 打印汇总报告
    print("\n" + "="*50)
    print("更新完成! 汇总报告:")
    print(f"成功更新: {updated_count} 个模块")
    
    if skipped_modules:
        print(f"\n跳过 {len(skipped_modules)} 个模块:")
        for module in skipped_modules:
            print(f"  - {module}")
    
    if error_modules:
        print(f"\n处理失败 {len(error_modules)} 个模块:")
        for module in error_modules:
            print(f"  - {module}")
    
    print("="*50)

if __name__ == "__main__":
    MODULES_DIR = "modules"
    
    if not os.path.exists(MODULES_DIR):
        print(f"错误: 找不到模块目录 '{MODULES_DIR}'")
        exit(1)
    
    print("开始更新模块入口点...")
    update_module_entry_points(MODULES_DIR)
