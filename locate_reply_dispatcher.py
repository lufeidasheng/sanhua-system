import os
import sys
import traceback
import importlib.util
import inspect

def find_all_reply_dispatcher_defs(root_dir):
    matches = []
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.endswith(".py"):
                fullpath = os.path.join(dirpath, filename)
                try:
                    with open(fullpath, "r", encoding="utf-8") as f:
                        content = f.read()
                    if "class ReplyDispatcher" in content:
                        matches.append(fullpath)
                except Exception as e:
                    print(f"读取文件出错: {fullpath} -> {e}")
    return matches

def print_sys_path():
    print("当前 sys.path 列表:")
    for p in sys.path:
        print(f"  {p}")

def import_and_inspect(module_path):
    try:
        spec = importlib.util.spec_from_file_location("reply_dispatcher_module", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        print(f"模块导入成功: {module_path}")
        
        cls = getattr(module, "ReplyDispatcher", None)
        if cls:
            print(f"找到 ReplyDispatcher 类，文件: {module_path}")
            print("类的方法列表:")
            for name, func in inspect.getmembers(cls, predicate=inspect.isfunction):
                print(f" - {name}")
        else:
            print("没有找到 ReplyDispatcher 类")
    except Exception:
        print(f"导入模块失败: {module_path}")
        traceback.print_exc()

def main():
    root_dir = os.path.abspath(".")
    print(f"项目根目录: {root_dir}")
    print_sys_path()

    print("\n搜索项目内所有定义了 ReplyDispatcher 的文件...")
    dispatcher_files = find_all_reply_dispatcher_defs(root_dir)
    if dispatcher_files:
        for f in dispatcher_files:
            print(f"  找到: {f}")
    else:
        print("未找到任何 ReplyDispatcher 类定义文件")

    print("\n尝试导入并检查这些模块:")
    for f in dispatcher_files:
        import_and_inspect(f)
        print("-" * 50)

if __name__ == "__main__":
    main()
