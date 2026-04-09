import os
import json
import importlib

MODULES_DIR = "modules"
RUN_ALL_SCRIPT = "run_all_entries.py"

def find_modules():
    """遍历modules目录，返回模块名和路径"""
    for name in os.listdir(MODULES_DIR):
        module_path = os.path.join(MODULES_DIR, name)
        if os.path.isdir(module_path):
            yield name, module_path

def update_manifest(module_path):
    """更新或创建manifest.json，写入is_entry=true"""
    manifest_path = os.path.join(module_path, "manifest.json")
    manifest = {}
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            try:
                manifest = json.load(f)
            except json.JSONDecodeError:
                print(f"⚠️ manifest.json 格式错误: {manifest_path}, 将重置内容")
                manifest = {}
    manifest["is_entry"] = True
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"✅ 更新 manifest.json：{manifest_path}")

def update_init_py(module_path):
    """给__init__.py追加入口引用from .module import entry，避免重复"""
    init_path = os.path.join(module_path, "__init__.py")
    content = ""
    if os.path.exists(init_path):
        with open(init_path, "r", encoding="utf-8") as f:
            content = f.read()
    entry_line = "from .module import entry"
    if entry_line not in content:
        with open(init_path, "a", encoding="utf-8") as f:
            if not content.endswith("\n"):
                f.write("\n")
            f.write(entry_line + "\n")
        print(f"✅ 更新 __init__.py：{init_path}")
    else:
        print(f"ℹ️ __init__.py 已包含入口引用：{init_path}")

def generate_run_all_script(entry_modules):
    """生成一个统一入口脚本，自动导入并调用所有入口模块的entry()函数"""
    lines = [
        "import importlib",
        "",
        "def run_all_entries():",
    ]
    for mod in entry_modules:
        lines.append(f"    mod = importlib.import_module('modules.{mod}.module')")
        lines.append(f"    if hasattr(mod, 'entry'):")
        lines.append(f"        print('启动入口模块：{mod}')")
        lines.append(f"        mod.entry()")
        lines.append("")
    lines.append("")
    lines.append("if __name__ == '__main__':")
    lines.append("    run_all_entries()")
    lines.append("")

    with open(RUN_ALL_SCRIPT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ 生成统一入口启动脚本：{RUN_ALL_SCRIPT}")

def main():
    entry_modules = []
    for name, path in find_modules():
        update_manifest(path)
        update_init_py(path)
        entry_modules.append(name)

    generate_run_all_script(entry_modules)
    print("🎉 所有入口模块注册并生成启动脚本完成！")

if __name__ == "__main__":
    main()
