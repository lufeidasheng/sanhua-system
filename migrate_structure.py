#!/usr/bin/env python3
"""
migrate_structure.py - 增强版

改进内容：
1. 修复核心目录映射路径
2. 增强备份文件排除逻辑
3. 添加空目录备份支持
4. 正确处理符号链接
5. 添加错误处理机制
6. 路径规范化处理
"""
import argparse, os, shutil, zipfile, datetime, sys
from pathlib import Path

# ====== 修复后的映射表 ======
MAPPING = {
    # ==== entry ====
    "modules/cli_entry":        "entry/cli_entry",
    "modules/gui_entry":        "entry/gui_entry",
    "modules/voice_entry":      "entry/voice_entry",
    "modules/voice_input":      "entry/voice_input",
    "register_and_run_entries.py": "entry/register_and_run_entries.py",
    "add_entry_func.py":        "entry/add_entry_func.py",

    # ==== core ==== (修复路径)
    "aicore":                   "core/aicore",
    "core.core2_0":                  "core/core.core2_0",  # 关键修复
    "system":                   "core/system",

    # ==== scaffold ====
    "module_standardizer.py":   "scaffold/module_standardizer.py",
    "health_checker.py":        "scaffold/health_checker.py",
    "standardize_modules.py":   "scaffold/standardize_modules.py",
    "scripts":                  "scaffold/scripts",

    # ==== modules ====
    "modules":                  "modules",
    "juzi":                     "modules/juzi",
    "ju_wu":                    "modules/ju_wu",

    # ==== dependencies ====
    "audio_env":                "dependencies/audio_env",
    "requirements.txt":         "dependencies/requirements.txt",
}

NEW_TOP_DIRS = [
    "entry", "core", "scaffold", "modules", "dependencies",
    "docs", "tests", "logs"
]

# ====== 增强版备份函数 ======
def backup_project(root: Path):
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    zip_name = root / f"backup_{ts}.zip"
    print(f"🔐 正在备份项目到 {zip_name}...")
    
    try:
        with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
            # 添加空目录处理
            for base_dir, dirs, files in os.walk(root):
                base_path = Path(base_dir)
                
                # 添加空目录
                if not files and not dirs:
                    rel_path = base_path.relative_to(root)
                    zf.write(base_dir, str(rel_path))
                
                # 添加文件
                for file in files:
                    full_path = base_path / file
                    
                    # 精确排除备份文件
                    if full_path.resolve() == zip_name.resolve():
                        continue
                        
                    rel_path = full_path.relative_to(root)
                    zf.write(full_path, str(rel_path))
                    
        print(f"✅ 备份完成 ({zip_name.stat().st_size/1024/1024:.2f} MB)")
        return zip_name
        
    except Exception as e:
        print(f"❌ 备份失败: {str(e)}")
        sys.exit(1)

# ====== 增强版移动函数 ======
def move_item(src: Path, dst: Path, dry: bool, log: list):
    if not src.exists():
        log.append(f"SKIP  {src} 不存在")
        return
        
    try:
        if dry:
            log.append(f"PLAN  {src} -> {dst}")
            return
            
        # 处理目标已存在的情况
        if dst.exists():
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
            log.append(f"DEL  删除已存在的 {dst}")
        
        # 创建父目录
        dst.parent.mkdir(parents=True, exist_ok=True)
        
        # 特殊处理符号链接
        if src.is_symlink():
            linkto = src.resolve()
            dst.symlink_to(linkto)
            src.unlink()
            log.append(f"LINK  {src} -> {dst} (符号链接)")
        # 移动普通文件/目录
        else:
            shutil.move(str(src), str(dst))
            log.append(f"MOVE  {src} -> {dst}")
            
    except Exception as e:
        error_msg = f"ERROR 移动失败 {src}: {str(e)}"
        log.append(error_msg)
        print(error_msg)

# ====== 主迁移函数 ======
def migrate(root: Path, dry_run: bool):
    # 创建目标目录结构
    for d in NEW_TOP_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    
    log = ["="*50, f"迁移开始: {datetime.datetime.now()}", "="*50]
    
    # 执行迁移
    for old_rel, new_rel in MAPPING.items():
        old_path = (root / old_rel).resolve()
        new_path = (root / new_rel).resolve()
        move_item(old_path, new_path, dry_run, log)
    
    # 保存日志
    log_path = root / "migrate_log.txt"
    log.append("\n" + "="*50)
    log.append(f"操作总数: {len(log)-4}")
    log.append(f"迁移状态: {'预演' if dry_run else '完成'}")
    
    log_path.write_text("\n".join(log), encoding="utf-8")
    print(f"\n{'-'*40}")
    print(f"📄 迁移日志已保存到 {log_path}")
    print(f"📋 操作摘要 (共 {len(MAPPING)} 项):")
    print("\n".join(log[3:10]) + "\n...")

# ====== CLI入口 ======
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="三花聚顶项目目录迁移工具",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--dry-run", 
        action="store_true",
        help="预演模式: 显示计划操作但不实际执行"
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="跳过项目备份 (不推荐)"
    )
    
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parent
    
    print("="*60)
    print("三花聚顶项目目录迁移工具")
    print("="*60)
    
    # 执行备份
    if not args.dry_run and not args.no_backup:
        backup_zip = backup_project(project_root)
        print(f"💾 备份位置: {backup_zip}")
    
    # 执行迁移
    migrate(project_root, args.dry_run)
    
    # 结果总结
    print("\n" + "="*60)
    if args.dry_run:
        print("⚠️ 预演完成 - 请检查迁移计划")
        print("执行实际迁移请运行: python migrate_structure.py")
    else:
        print("🎉 迁移完成! 下一步操作:")
        print("1. 验证目录结构")
        print("2. 更新所有模块的导入路径")
        print("3. 运行测试脚本 test_project_structure.py")
    print("="*60)
