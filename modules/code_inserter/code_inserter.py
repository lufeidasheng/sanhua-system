"""
三花聚顶 · code_inserter 标准功能模块
作者: 三花聚顶开发团队
描述: 多语言代码插入、备份、差异对比工具。支持 marker、函数后插入，兼容主控自动化/AI/CLI/GUI。
"""

import os
import re
import ast
import difflib
import shutil
import datetime
import logging
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

# === 日志优化 ===
logger = logging.getLogger("code_inserter")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "logs", "code_inserter"))
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "code_inserter.log")
if not logger.handlers:
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

LANGUAGE_COMMENTS = {
    '.py': '#', '.js': '//', '.ts': '//', '.java': '//', '.c': '//', '.cpp': '//', '.h': '//',
    '.go': '//', '.rs': '//', '.sh': '#', '.rb': '#', '.php': '//', '.swift': '//', '.kt': '//',
    '.scala': '//', '.m': '//', '.pl': '#', '.lua': '--', '.sql': '--', '.html': '<!--',
    '.css': '/*', '.scss': '//', '.sass': '//', '.less': '//', '.vue': '//', '.jsx': '//',
    '.tsx': '//', '.dart': '//',
}

class CodeInserter:
    def __init__(self, backup_dir=None):
        self.backup_dir = backup_dir or os.path.expanduser("~/.aicore/backups")
        os.makedirs(self.backup_dir, exist_ok=True)
        logger.info(f"代码插入器初始化完成，备份目录: {self.backup_dir}")

    def _get_file_comment_style(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        return LANGUAGE_COMMENTS.get(ext, '#')

    def _create_backup(self, file_path: str) -> str:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(self.backup_dir, f"{os.path.basename(file_path)}_backup_{timestamp}")
        try:
            shutil.copy2(file_path, backup_file)
            logger.info(f"已创建备份: {backup_file}")
            return backup_file
        except Exception as e:
            logger.exception(f"创建备份失败: {e}")
            return ""

    def _validate_python_code(self, code: str) -> bool:
        try:
            ast.parse(code)
            return True
        except SyntaxError as e:
            logger.error(f"Python语法错误: {e}")
            return False

    def _validate_code(self, code: str, file_path: str) -> bool:
        if not code.strip():
            logger.warning("尝试插入空代码")
            return False
        if file_path.endswith('.py'):
            return self._validate_python_code(code)
        return True

    def _find_insertion_point(self, source_code: str, marker: str) -> int:
        if marker in source_code:
            return source_code.index(marker)
        lines = source_code.splitlines()
        for i, line in enumerate(lines):
            if marker.lower() in line.lower():
                logger.warning(f"使用模糊匹配插入点: 第{i+1}行")
                return sum(len(l)+1 for l in lines[:i])
        # 常见默认插入点
        for cm in ["# INSERTION POINT", "// INSERTION POINT", "/* INSERTION POINT */"]:
            if cm in source_code:
                logger.info(f"使用默认插入点: {cm}")
                return source_code.index(cm)
        logger.info("未找到插入点，将在文件末尾插入代码")
        return len(source_code)

    def insert_code_at_marker(
        self, source_code: str, insert_code: str, marker: str = "# >>> 插入点",
        file_path: str = "", context_lines: int = 3
    ) -> Tuple[str, Dict[str, Any]]:
        if not self._validate_code(insert_code, file_path):
            return source_code, {"error": "代码验证失败"}
        insert_index = self._find_insertion_point(source_code, marker)
        pre_context = source_code[max(0, insert_index-100):insert_index].splitlines()[-context_lines:]
        post_context = source_code[insert_index:insert_index+100].splitlines()[:context_lines]
        new_code = source_code[:insert_index] + "\n\n" + insert_code.rstrip() + "\n\n" + source_code[insert_index:]
        diff = list(difflib.unified_diff(source_code.splitlines(), new_code.splitlines(), lineterm=''))[2:]
        return new_code, {
            "insertion_point": insert_index,
            "pre_context": "\n".join(pre_context),
            "post_context": "\n".join(post_context),
            "diff": "\n".join(diff),
            "marker_found": marker in source_code
        }

    def save_code_to_file(self, code: str, path: str) -> Dict[str, Any]:
        try:
            file_exists = os.path.exists(path)
            backup_path = self._create_backup(path) if file_exists else ""
            if file_exists and not os.access(path, os.W_OK):
                logger.error(f"文件不可写: {path}")
                return {"status": "error", "message": "文件不可写"}
            with open(path, 'w', encoding='utf-8') as f:
                f.write(code)
            if not file_exists:
                os.chmod(path, 0o644)
            logger.info(f"已成功保存修改到: {path}")
            return {"status": "success", "path": path, "backup": backup_path, "file_created": not file_exists}
        except Exception as e:
            logger.exception(f"保存失败: {e}")
            return {"status": "error", "message": str(e)}

    def insert_code_into_file(
        self, file_path: str, insert_code: str, marker: str = "# >>> 插入点", auto_save: bool = False
    ) -> Dict[str, Any]:
        result = {"file_path": file_path, "auto_save": auto_save, "status": "error", "validation": False}
        try:
            if not os.path.exists(file_path):
                logger.warning(f"文件不存在，将创建: {file_path}")
                Path(file_path).touch()
            with open(file_path, 'r', encoding='utf-8') as f:
                original_code = f.read()
            if not self._validate_code(insert_code, file_path):
                result["message"] = "插入的代码未通过验证"
                return result
            result["validation"] = True
            new_code, details = self.insert_code_at_marker(original_code, insert_code, marker, file_path)
            result["details"] = details
            if auto_save:
                save_result = self.save_code_to_file(new_code, file_path)
                result.update(save_result)
                result["status"] = save_result.get("status", "error")
            else:
                result["new_code"] = new_code
                result["status"] = "success"
                result["message"] = "代码已生成但未保存"
            return result
        except Exception as e:
            logger.exception(f"文件操作失败: {e}")
            result["message"] = str(e)
            return result

    def insert_code_after_function(
        self, file_path: str, insert_code: str, function_name: str, auto_save: bool = False
    ) -> Dict[str, Any]:
        if not file_path.endswith('.py'):
            logger.error("函数后插入目前仅支持Python文件")
            return {"status": "error", "message": "函数后插入目前仅支持Python文件"}
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source_code = f.read()
            tree = ast.parse(source_code)
            function_node = None
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == function_name:
                    function_node = node
                    break
            if not function_node:
                logger.error(f"未找到函数: {function_name}")
                return {"status": "error", "message": f"未找到函数: {function_name}"}
            function_end_line = function_node.end_lineno
            lines = source_code.splitlines()
            insert_line = function_end_line
            while insert_line < len(lines) and lines[insert_line].strip() != "":
                insert_line += 1
            if insert_line >= len(lines):
                insert_line = function_end_line
            new_lines = lines[:insert_line] + [""] + insert_code.splitlines() + lines[insert_line:]
            new_code = "\n".join(new_lines)
            if auto_save:
                save_result = self.save_code_to_file(new_code, file_path)
                save_result["function"] = function_name
                return save_result
            else:
                return {"status": "success", "new_code": new_code, "function": function_name, "insert_line": insert_line}
        except Exception as e:
            logger.exception(f"函数后插入失败: {e}")
            return {"status": "error", "message": str(e)}

    def generate_code_signature(self, code: str) -> str:
        clean_code = re.sub(r'\s+|#.*', '', code)
        return hashlib.sha256(clean_code.encode('utf-8')).hexdigest()[:16]

# === 动作注册/入口 ===

_inserter = CodeInserter()

def insert_code(core, params: dict) -> Dict[str, Any]:
    file_path = params.get("file_path", "")
    insert_code_str = params.get("insert_code", "")
    marker = params.get("marker", "# >>> 插入点")
    auto_save = params.get("auto_save", False)
    strategy = params.get("insertion_strategy", "marker")
    signature = _inserter.generate_code_signature(insert_code_str)
    logger.info(f"插入代码签名: {signature}")
    if not file_path:
        return {"status": "error", "message": "参数 file_path 必须提供"}
    if not insert_code_str:
        return {"status": "error", "message": "参数 insert_code 必须提供"}
    if strategy == "after_function":
        function_name = params.get("function_name")
        if not function_name:
            return {"status": "error", "message": "函数后插入需要 function_name"}
        return _inserter.insert_code_after_function(file_path, insert_code_str, function_name, auto_save)
    else:
        return _inserter.insert_code_into_file(file_path, insert_code_str, marker, auto_save)

def register():
    return {"insert_code": insert_code}

def register_actions(dispatcher):
    dispatcher.register_action(
        "insert_code",
        insert_code,
        description="在源代码文件中插入代码片段",
        parameters={
            "file_path": {"type": "string", "description": "目标文件路径"},
            "insert_code": {"type": "string", "description": "要插入的代码"},
            "marker": {"type": "string", "description": "插入点标记", "optional": True},
            "auto_save": {"type": "boolean", "description": "是否自动保存", "optional": True},
            "insertion_strategy": {
                "type": "string",
                "description": "插入策略 (marker 或 after_function)",
                "optional": True
            },
            "function_name": {
                "type": "string",
                "description": "after_function 策略时函数名",
                "optional": True
            }
        },
        module_name="modules.code_inserter"
    )
    logger.info("代码插入模块动作注册完成")

if __name__ == "__main__":
    # 基础测试
    test_file = "/tmp/test_insert.py"
    with open(test_file, 'w') as f:
        f.write("# 测试文件\n\ndef existing_func():\n    pass\n\n# >>> 插入点")
    result = insert_code(None, {
        "file_path": test_file,
        "insert_code": "\ndef new_func():\n    print('新功能')",
        "auto_save": True
    })
    print("插入结果:", result)
    result = insert_code(None, {
        "file_path": test_file,
        "insert_code": "    # 函数后添加的代码\n    print('函数后插入')",
        "insertion_strategy": "after_function",
        "function_name": "existing_func",
        "auto_save": True
    })
    print("函数后插入结果:", result)
    with open(test_file, 'r') as f:
        print("\n修改后的文件内容:")
        print(f.read())
