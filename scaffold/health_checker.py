import ast
import os
import json
import argparse
import logging
import tokenize
import io
import hashlib
import time
from typing import List, Tuple, Dict, Optional, Set
from dataclasses import dataclass, field
import multiprocessing
from functools import partial
from datetime import datetime
from collections import defaultdict
import html

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 默认忽略的目录和文件
DEFAULT_IGNORE_DIRS = {'.git', '.svn', '.hg', '__pycache__', 'venv', 'env', 'node_modules', '.idea', '.vscode'}
DEFAULT_IGNORE_FILES = {'setup.py', 'conftest.py'}

# 配置常量
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_COMPLEXITY = 15
MIN_COMMENT_RATE = 10
MAX_RETRIES = 3
CACHE_VERSION = "v1.3"

@dataclass
class CodeStats:
    """存储代码分析结果的不可变数据结构"""
    filepath: str
    module: Optional[str] = None
    syntax_ok: bool = True
    func_count: int = 0
    async_func_count: int = 0
    class_count: int = 0
    comment_lines: int = 0
    code_lines: int = 0
    total_lines: int = 0
    complexity: float = 0.0
    imports: Set[str] = field(default_factory=set)
    risk_level: str = "LOW"
    error: Optional[str] = None
    last_modified: float = 0.0
    file_hash: str = ""

class ProjectAnalyzer:
    """项目分析器主类"""
    def __init__(self, root_dir: str, ignore_dirs: Optional[set] = None, 
                 ignore_files: Optional[set] = None, cache_file: Optional[str] = None):
        self.root_dir = os.path.abspath(root_dir)
        self.ignore_dirs = ignore_dirs or DEFAULT_IGNORE_DIRS
        self.ignore_files = ignore_files or DEFAULT_IGNORE_FILES
        self.module_dirs = set()
        self.cache_file = cache_file or os.path.join(self.root_dir, ".code_health_cache.json")
        self.cache = self._load_cache()
        self._validate_root_dir()
    
    def _validate_root_dir(self):
        """验证根目录是否存在"""
        if not os.path.isdir(self.root_dir):
            raise FileNotFoundError(f"目录不存在: {self.root_dir}")
    
    def _load_cache(self) -> Dict[str, dict]:
        """加载分析缓存"""
        if not os.path.exists(self.cache_file):
            return {}
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                cache = json.load(f)
                return cache.get("data", {}) if cache.get("version") == CACHE_VERSION else {}
        except Exception as e:
            logger.error(f"加载缓存失败: {str(e)}")
            return {}
    
    def _save_cache(self):
        """保存分析缓存"""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump({"version": CACHE_VERSION, "data": self.cache}, f, indent=2)
        except Exception as e:
            logger.error(f"保存缓存失败: {str(e)}")
    
    def _file_hash(self, filepath: str) -> str:
        """计算文件哈希值"""
        try:
            with open(filepath, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception:
            return ""
    
    def _should_ignore(self, path: str) -> bool:
        """判断路径是否应忽略"""
        rel_path = os.path.relpath(path, self.root_dir)
        if any(part in self.ignore_dirs for part in rel_path.split(os.sep)):
            return True
        return os.path.isfile(path) and os.path.basename(path) in self.ignore_files
    
    def _calculate_complexity(self, node) -> int:
        """计算AST节点的圈复杂度"""
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.And, ast.Or, 
                                ast.Try, ast.ExceptHandler, ast.With)):
                complexity += 1
            elif isinstance(child, (ast.BoolOp, ast.IfExp)):
                complexity += len(child.values) - 1
        return complexity
    
    def _count_lines_with_tokenize(self, filepath: str) -> Tuple[int, int]:
        """使用tokenize统计行数"""
        try:
            with open(filepath, "rb") as f:
                tokens = tokenize.tokenize(f.readline)
                comment_lines, code_lines = set(), set()
                for token in tokens:
                    if token.type == tokenize.COMMENT:
                        comment_lines.add(token.start[0])
                    elif token.type == tokenize.STRING:
                        for line in range(token.start[0], token.end[0] + 1):
                            comment_lines.add(line)
                    elif token.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.ENCODING):
                        code_lines.add(token.start[0])
                return len(comment_lines), len(code_lines)
        except Exception:
            return 0, 0
    
    def _count_lines_fallback(self, source: str) -> Tuple[int, int]:
        """回退的行计数方法"""
        lines = source.splitlines()
        in_multiline_comment = False
        comment_lines = code_lines = 0
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if in_multiline_comment:
                comment_lines += 1
                in_multiline_comment = not (stripped.endswith('"""') or stripped.endswith("'''"))
            elif stripped.startswith('#'):
                comment_lines += 1
            elif stripped.startswith('"""') or stripped.startswith("'''"):
                comment_lines += 1
                in_multiline_comment = not (stripped.endswith('"""') or stripped.endswith("'''"))
            else:
                code_lines += 1
        return comment_lines, code_lines
    
    def analyze_py_file(self, filepath: str) -> Optional[CodeStats]:
        """分析单个Python文件"""
        if not os.path.isfile(filepath) or os.path.getsize(filepath) > MAX_FILE_SIZE:
            return None
        
        file_hash = self._file_hash(filepath)
        last_modified = os.path.getmtime(filepath)
        
        # 缓存检查
        if cached := self.cache.get(filepath):
            if cached["file_hash"] == file_hash and cached["last_modified"] == last_modified:
                return CodeStats(**{k: v for k, v in cached.items() if k in CodeStats.__annotations__})
        
        stats = CodeStats(filepath=filepath, last_modified=last_modified, file_hash=file_hash)
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()
                stats.total_lines = len(source.splitlines())
            
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    stats.complexity += self._calculate_complexity(node)
                    stats.func_count += 1 if isinstance(node, ast.FunctionDef) else 0
                    stats.async_func_count += 1 if isinstance(node, ast.AsyncFunctionDef) else 0
                elif isinstance(node, ast.ClassDef):
                    stats.class_count += 1
                    stats.complexity += self._calculate_complexity(node)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    stats.imports.update(alias.name for alias in node.names)
            
            if total_funcs := stats.func_count + stats.async_func_count + stats.class_count:
                stats.complexity = round(stats.complexity / total_funcs, 1)
            
            stats.comment_lines, stats.code_lines = self._count_lines_with_tokenize(filepath) or \
                                                   self._count_lines_fallback(source)
            
            comment_rate = (stats.comment_lines / stats.code_lines * 100) if stats.code_lines else 0
            stats.risk_level = "HIGH" if stats.complexity > MAX_COMPLEXITY and comment_rate < MIN_COMMENT_RATE else \
                              "MEDIUM" if stats.complexity > MAX_COMPLEXITY or comment_rate < MIN_COMMENT_RATE else "LOW"
            
            self.cache[filepath] = stats.__dict__
            return stats
            
        except SyntaxError as e:
            stats.syntax_ok = False
            stats.error = f"SyntaxError: {e.msg} at line {e.lineno}"
        except Exception as e:
            stats.syntax_ok = False
            stats.error = f"{type(e).__name__}: {str(e)}"
        
        self.cache[filepath] = stats.__dict__
        return stats
    
    def collect_python_files(self) -> List[str]:
        """递归收集所有Python文件"""
        py_files = []
        MODULE_MARKERS = {'__init__.py', 'setup.py', 'pyproject.toml', 'manifest.json'}
        
        for dirpath, dirnames, filenames in os.walk(self.root_dir):
            dirnames[:] = [d for d in dirnames if d not in self.ignore_dirs]
            if any(marker in filenames for marker in MODULE_MARKERS):
                self.module_dirs.add(dirpath)
            py_files.extend(
                os.path.join(dirpath, f) for f in filenames 
                if f.endswith(".py") and not self._should_ignore(os.path.join(dirpath, f))
            )
        return py_files
    
    def scan_project(self) -> List[CodeStats]:
        """扫描项目目录并分析所有Python文件"""
        logger.info(f"开始扫描目录: {self.root_dir}")
        py_files = self.collect_python_files()
        logger.info(f"找到 {len(py_files)} 个Python文件")
        
        with multiprocessing.Pool(min(8, max(1, len(py_files)//100))) as pool:
            results = list(pool.imap(self._analyze_file, py_files))
        
        self._save_cache()
        return [r for r in results if r is not None]
    
    def _analyze_file(self, filepath: str) -> Optional[CodeStats]:
        """分析单个文件并添加模块信息"""
        try:
            stats = self.analyze_py_file(filepath)
            if not stats:
                return None
            
            for mod_dir in self.module_dirs:
                if filepath.startswith(mod_dir):
                    stats.module = os.path.relpath(mod_dir, self.root_dir).replace(os.sep, "/")
                    break
            stats.module = stats.module or "非模块文件"
            return stats
        except Exception as e:
            logger.error(f"文件分析异常: {filepath} - {str(e)}")
            return None

class ReportGenerator:
    """报告生成器"""
    @staticmethod
    def generate_report(results: List[CodeStats], output_file: str, root_dir: str, html_report: bool = False):
        """生成报告"""
        if html_report:
            ReportGenerator.generate_html_report(results, output_file, root_dir)
        else:
            ReportGenerator.generate_markdown_report(results, output_file, root_dir)
    
    @staticmethod
    def generate_markdown_report(results: List[CodeStats], output_file: str, root_dir: str):
        """生成Markdown格式报告"""
        module_summary, dep_graph = ReportGenerator._aggregate_results(results)
        
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(ReportGenerator._md_header(root_dir, results))
            f.write(ReportGenerator._md_module_table(module_summary))
            f.write(ReportGenerator._md_overall_stats(results))
            f.write(ReportGenerator._md_dependency_graph(dep_graph, module_summary))
            f.write(ReportGenerator._md_file_table(results, root_dir))
        
        logger.info(f"Markdown代码健康度报告已生成: {output_file}")
    
    @staticmethod
    def _md_header(root_dir: str, results: List[CodeStats]) -> str:
        """生成Markdown报告头部"""
        return (
            f"# 三花聚顶项目代码健康度扫描报告\n\n"
            f"**扫描目录**: `{os.path.abspath(root_dir)}`\n"
            f"**扫描时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"**文件总数**: {len(results)}\n"
            f"**模块数量**: {len(set(r.module for r in results))}\n"
            f"**高风险文件**: {sum(1 for r in results if r.risk_level == 'HIGH')}\n\n"
        )
    
    @staticmethod
    def _md_module_table(module_summary: Dict[str, dict]) -> str:
        """生成Markdown模块表格"""
        table = [
            "## 模块统计概览\n",
            "| 模块名称 | 文件数 | 语法错误 | 函数 | 异步函数 | 类 | 注释行 | 代码行 | 注释率 | 平均复杂度 | 风险文件 |",
            "|----------|--------|----------|------|----------|----|--------|--------|--------|------------|----------|"
        ]
        
        for mod, data in sorted(module_summary.items()):
            comment_rate = (data["comment_lines"] / data["code_lines"] * 100) if data["code_lines"] > 0 else 0
            avg_complexity = data["complexity"] / data["file_count"] if data["file_count"] > 0 else 0
            
            table.append(
                f"| {mod} | {data['file_count']} | {data['syntax_errors']} | "
                f"{data['func_count']} | {data['async_func_count']} | {data['class_count']} | "
                f"{data['comment_lines']} | {data['code_lines']} | {comment_rate:.1f}% | "
                f"{avg_complexity:.1f} | {data['high_risk_files']} |"
            )
        return "\n".join(table) + "\n\n"
    
    @staticmethod
    def _md_overall_stats(results: List[CodeStats]) -> str:
        """生成Markdown总体统计"""
        total_files = len(results)
        error_files = sum(1 for r in results if not r.syntax_ok)
        high_risk_files = sum(1 for r in results if r.risk_level == "HIGH")
        total_funcs = sum(r.func_count for r in results)
        total_async_funcs = sum(r.async_func_count for r in results)
        total_classes = sum(r.class_count for r in results)
        total_comments = sum(r.comment_lines for r in results)
        total_code = sum(r.code_lines for r in results)
        total_complexity = sum(r.complexity for r in results)
        avg_complexity = total_complexity / total_files if total_files > 0 else 0
        comment_rate = (total_comments / total_code * 100) if total_code > 0 else 0
        
        return (
            "## 项目总体统计\n\n"
            f"- **文件总数**: {total_files}\n"
            f"- **语法错误文件**: {error_files} ({error_files/total_files*100:.1f}%)\n"
            f"- **高风险文件**: {high_risk_files}\n"
            f"- **函数总数**: {total_funcs}\n"
            f"- **异步函数**: {total_async_funcs}\n"
            f"- **类总数**: {total_classes}\n"
            f"- **注释行**: {total_comments}\n"
            f"- **代码行**: {total_code}\n"
            f"- **平均复杂度**: {avg_complexity:.1f}\n"
            f"- **注释率**: {comment_rate:.1f}%\n\n"
        )
    
    @staticmethod
    def _md_dependency_graph(dep_graph: Dict[str, List[str]], module_summary: Dict[str, dict]) -> str:
        """生成Markdown依赖图"""
        graph_lines = ["## 模块依赖关系\n```mermaid\ngraph TD"]
        for source, targets in dep_graph.items():
            for target in targets:
                if target in module_summary:
                    graph_lines.append(f"    {source} --> {target}")
        graph_lines.append("```\n")
        return "\n".join(graph_lines) + "\n"
    
    @staticmethod
    def _md_file_table(results: List[CodeStats], root_dir: str) -> str:
        """生成Markdown文件表格"""
        table = [
            "## 详细文件清单\n",
            "| 文件路径 | 模块 | 风险等级 | 语法正确 | 函数 | 异步函数 | 类 | 注释行 | 代码行 | 复杂度 |",
            "|----------|------|----------|----------|------|----------|----|--------|--------|--------|"
        ]
        
        for result in sorted(results, key=lambda x: (x.risk_level, x.complexity), reverse=True):
            risk_icon = "🟥" if result.risk_level == "HIGH" else "🟨" if result.risk_level == "MEDIUM" else "🟩"
            table.append(
                f"| {os.path.relpath(result.filepath, root_dir)} | {result.module} | {risk_icon} {result.risk_level} | "
                f"{'✓' if result.syntax_ok else '✗'} | {result.func_count} | "
                f"{result.async_func_count} | {result.class_count} | {result.comment_lines} | "
                f"{result.code_lines} | {result.complexity} |"
            )
        return "\n".join(table)
    
    @staticmethod
    def generate_html_report(results: List[CodeStats], output_file: str, root_dir: str):
        """生成HTML报告"""
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(ReportGenerator._render_html_template(results, root_dir))
        logger.info(f"HTML代码健康度报告已生成: {output_file}")
    
    @staticmethod
    def _render_html_template(results: List[CodeStats], root_dir: str) -> str:
        """渲染HTML模板"""
        module_summary, dep_graph = ReportGenerator._aggregate_results(results)
        complexities = json.dumps([r.complexity for r in results])
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        abs_root = os.path.abspath(root_dir)
        file_count = len(results)
        module_count = len(module_summary)
        high_risk_count = sum(1 for r in results if r.risk_level == "HIGH")
        
        # 生成模块表格行
        module_rows = []
        for mod, data in sorted(module_summary.items()):
            comment_rate = (data["comment_lines"] / data["code_lines"] * 100) if data["code_lines"] > 0 else 0
            avg_complexity = data["complexity"] / data["file_count"] if data["file_count"] > 0 else 0
            module_rows.append(f"""
                <tr>
                    <td>{mod}</td>
                    <td>{data['file_count']}</td>
                    <td>{data['syntax_errors']}</td>
                    <td>{data['func_count']}</td>
                    <td>{data['async_func_count']}</td>
                    <td>{data['class_count']}</td>
                    <td>{data['comment_lines']}</td>
                    <td>{data['code_lines']}</td>
                    <td>{comment_rate:.1f}%</td>
                    <td>{avg_complexity:.1f}</td>
                    <td>{data['high_risk_files']}</td>
                </tr>
            """)
        
        # 生成文件表格行
        file_rows = []
        for result in sorted(results, key=lambda x: (x.risk_level, x.complexity), reverse=True):
            file_rows.append(f"""
                <tr class="risk-{result.risk_level.lower()}">
                    <td>{os.path.relpath(result.filepath, root_dir)}</td>
                    <td>{result.module}</td>
                    <td>{result.risk_level}</td>
                    <td>{"✓" if result.syntax_ok else "✗"}</td>
                    <td>{result.func_count}</td>
                    <td>{result.async_func_count}</td>
                    <td>{result.class_count}</td>
                    <td>{result.comment_lines}</td>
                    <td>{result.code_lines}</td>
                    <td>{result.complexity}</td>
                </tr>
            """)
        
        # 生成依赖关系图
        dep_graph_lines = []
        for source, targets in dep_graph.items():
            for target in targets:
                if target in module_summary:
                    dep_graph_lines.append(f"{source}-->{target}")
        
        graph_lines_joined = "\n                        ".join(dep_graph_lines)
        complexities_str = json.dumps([r.complexity for r in results], separators=(",", ":"))
        
        return rf"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <title>三花聚顶项目代码健康度报告</title>
            <script src="https://cdn.jsdelivr.net/npm/mermaid@10.6.1/dist/mermaid.min.js"></script>
            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .container {{ max-width: 1200px; margin: 0 auto; }}
                .card {{ background: #f9f9f9; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
                tr:hover {{ background-color: #f5f5f5; }}
                .high-risk {{ background-color: #ffdddd; }}
                .medium-risk {{ background-color: #fff3cd; }}
                .filters {{ margin: 20px 0; padding: 10px; background: #eee; border-radius: 4px; }}
                .chart-container {{ height: 400px; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>三花聚顶项目代码健康度扫描报告</h1>
                <div class="card">
                    <p><strong>扫描目录</strong>: {html.escape(abs_root)}</p>
                    <p><strong>扫描时间</strong>: {timestamp}</p>
                    <p><strong>文件总数</strong>: {file_count}</p>
                    <p><strong>模块数量</strong>: {module_count}</p>
                    <p><strong>高风险文件</strong>: {high_risk_count}</p>
                </div>
                
                <div class="filters">
                    <label><input type="checkbox" id="show-high-risk" checked> 显示高风险</label>
                    <label><input type="checkbox" id="show-medium-risk" checked> 显示中风险</label>
                    <label><input type="checkbox" id="show-low-risk" checked> 显示低风险</label>
                    <label>最小复杂度: <input type="number" id="min-complexity" min="0" max="50" step="0.1" value="0"></label>
                    <button onclick="applyFilters()">应用筛选</button>
                </div>
                
                <div class="card">
                    <h2>模块统计概览</h2>
                    <table id="module-table">
                        <thead>
                            <tr>
                                <th>模块名称</th><th>文件数</th><th>语法错误</th><th>函数</th><th>异步函数</th>
                                <th>类</th><th>注释行</th><th>代码行</th><th>注释率</th><th>平均复杂度</th><th>风险文件</th>
                            </tr>
                        </thead>
                        <tbody>
                            {''.join(module_rows)}
                        </tbody>
                    </table>
                </div>
                
                <div class="card">
                    <h2>模块依赖关系</h2>
                    <div class="mermaid">
                        graph TD
                        {graph_lines_joined}
                    </div>
                </div>
                
                <div class="card">
                    <h2>详细文件清单</h2>
                    <table id="file-table">
                        <thead>
                            <tr>
                                <th>文件路径</th><th>模块</th><th>风险等级</th><th>语法正确</th><th>函数</th>
                                <th>异步函数</th><th>类</th><th>注释行</th><th>代码行</th><th>复杂度</th>
                            </tr>
                        </thead>
                        <tbody>
                            {''.join(file_rows)}
                        </tbody>
                    </table>
                </div>
                
                <div class="card">
                    <h2>复杂度分布</h2>
                    <div class="chart-container">
                        <canvas id="complexityChart"></canvas>
                    </div>
                </div>
            </div>
            
            <script>
                mermaid.initialize({{ startOnLoad: true }});
                
                function applyFilters() {{
                    const showHigh = document.getElementById('show-high-risk').checked;
                    const showMedium = document.getElementById('show-medium-risk').checked;
                    const showLow = document.getElementById('show-low-risk').checked;
                    const minComplexity = parseFloat(document.getElementById('min-complexity').value) || 0;
                    
                    document.querySelectorAll('#file-table tbody tr').forEach(row => {{
                        const risk = row.className.includes('high') ? 'high' : 
                                    row.className.includes('medium') ? 'medium' : 'low';
                        const complexity = parseFloat(row.cells[9].textContent);
                        row.style.display = 
                            ((risk === 'high' && showHigh) || (risk === 'medium' && showMedium) || (risk === 'low' && showLow)) &&
                            complexity >= minComplexity ? '' : 'none';
                    }});
                }}
                
                document.addEventListener('DOMContentLoaded', () => {{
                    new Chart(document.getElementById('complexityChart').getContext('2d'), {{
                        type: 'bar',
                        data: {{
                            datasets: [{{
                                label: '文件复杂度分布',
                                data: {complexities_str},
                                backgroundColor: {complexities_str}.map(c => 
                                    c > 15 ? 'rgba(255, 99, 132, 0.7)' :
                                    c > 10 ? 'rgba(255, 159, 64, 0.7)' : 'rgba(75, 192, 192, 0.7)'
                                )
                            }}]
                        }},
                        options: {{
                            scales: {{
                                y: {{ beginAtZero: true, title: {{ display: true, text: '文件数量' }} }},
                                x: {{ title: {{ display: true, text: '复杂度值' }} }}
                            }}
                        }}
                    }});
                }});
            </script>
        </body>
        </html>
        """
    
    @staticmethod
    def _aggregate_results(results: List[CodeStats]) -> Tuple[Dict[str, dict], Dict[str, List[str]]]:
        """聚合模块统计结果和依赖关系"""
        module_summary = defaultdict(lambda: {
            "file_count": 0, "syntax_errors": 0, "func_count": 0, "async_func_count": 0,
            "class_count": 0, "comment_lines": 0, "code_lines": 0, "complexity": 0.0, "high_risk_files": 0
        })
        dep_graph = defaultdict(list)
        
        for item in results:
            mod = item.module or "未分类"
            module_summary[mod]["file_count"] += 1
            module_summary[mod]["syntax_errors"] += 0 if item.syntax_ok else 1
            module_summary[mod]["func_count"] += item.func_count
            module_summary[mod]["async_func_count"] += item.async_func_count
            module_summary[mod]["class_count"] += item.class_count
            module_summary[mod]["comment_lines"] += item.comment_lines
            module_summary[mod]["code_lines"] += item.code_lines
            module_summary[mod]["complexity"] += item.complexity
            module_summary[mod]["high_risk_files"] += 1 if item.risk_level == "HIGH" else 0
            
            for imp in item.imports:
                if imp_module := imp.split('.')[0]:
                    if imp_module != mod:
                        dep_graph[mod].append(imp_module)
        
        return module_summary, dep_graph

def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description="三花聚顶项目代码健康度扫描器")
    parser.add_argument("root_dir", help="项目根目录路径")
    parser.add_argument("-o", "--output", default="health_report.md", help="报告输出文件")
    parser.add_argument("-f", "--format", choices=["markdown", "html"], default="markdown", help="报告输出格式")
    parser.add_argument("--cache", action="store_true", help="启用分析缓存")
    parser.add_argument("--ignore-dirs", nargs="+", default=list(DEFAULT_IGNORE_DIRS), help="要忽略的目录列表")
    parser.add_argument("--ignore-files", nargs="+", default=list(DEFAULT_IGNORE_FILES), help="要忽略的文件列表")
    
    args = parser.parse_args()
    multiprocessing.set_start_method("spawn")
    
    try:
        analyzer = ProjectAnalyzer(
            root_dir=args.root_dir,
            ignore_dirs=set(args.ignore_dirs),
            ignore_files=set(args.ignore_files),
            cache_file=os.path.join(args.root_dir, ".code_health_cache.json") if args.cache else None
        )
        
        start_time = time.time()
        results = analyzer.scan_project()
        logger.info(f"分析完成，共处理 {len(results)} 个文件，耗时 {time.time()-start_time:.2f} 秒")
        
        output_file = args.output
        if args.format == "html" and not output_file.endswith(".html"):
            output_file = os.path.splitext(output_file)[0] + ".html"
        
        ReportGenerator.generate_report(
            results, output_file, args.root_dir, html_report=(args.format == "html")
        )
    except Exception as e:
        logger.error(f"分析失败: {str(e)}", exc_info=True)
        exit(1)

if __name__ == "__main__":
    main()
