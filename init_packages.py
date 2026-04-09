#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
自动初始化Python包脚本 - 增强版
功能：在指定目录及其子目录中创建缺失的 __init__.py 文件
"""

import os
import sys

def create_init_files(directory, verbose=False):
    """
    递归遍历目录并创建缺失的 __init__.py 文件
    
    参数:
        directory: 要处理的根目录
        verbose: 是否显示详细输出
    """
    count = 0
    
    for root, dirs, files in os.walk(directory):
        # 跳过不需要处理的目录
        skip_dirs = ["__pycache__", "venv", "site-packages", "dist", "build", "node_modules"]
        if any(skip_dir in root for skip_dir in skip_dirs):
            if verbose:
                print(f"⏩ 跳过目录: {root}")
            continue
            
        # 检查是否需要创建 __init__.py
        if "__init__.py" not in files:
            init_path = os.path.join(root, "__init__.py")
            
            # 创建空文件
            with open(init_path, "w") as f:
                if verbose:
                    print(f"✅ 创建: {init_path}")
                count += 1
                
    return count

def main():
    # 默认处理目录（如果未指定参数）
    default_dirs = [
        "aicore",
        "core2.0",
        "gui",
        "ju_wu",
        "modules",
        "system"
    ]
    
    # 检查命令行参数
    if len(sys.argv) > 1:
        directories = sys.argv[1:]
        verbose = "-v" in sys.argv or "--verbose" in sys.argv
    else:
        # 使用默认目录
        directories = default_dirs
        verbose = True
        print("ℹ️ 未指定目录，使用默认目录集")

    print("🚀 开始初始化Python包结构...")
    
    total_count = 0
    for directory in directories:
        if not os.path.exists(directory):
            print(f"⚠️  目录不存在: {directory}")
            continue
            
        print(f"\n🔍 扫描目录: {directory}")
        count = create_init_files(directory, verbose)
        total_count += count
        print(f"  创建了 {count} 个 __init__.py 文件")

    print(f"\n🎉 完成! 总共创建了 {total_count} 个 __init__.py 文件")

if __name__ == "__main__":
    main()
