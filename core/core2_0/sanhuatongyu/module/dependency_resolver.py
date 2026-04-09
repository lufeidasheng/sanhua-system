import networkx as nx
from typing import Dict, List, Optional, Set
import packaging.version
from packaging.specifiers import SpecifierSet, InvalidSpecifier

from core.core2_0.sanhuatongyu.logger import get_logger

logger = get_logger('dep_resolver')

# === 依赖异常体系 ===
class VersionConflictError(Exception):
    """版本冲突异常基类"""
    pass

class CircularDependencyError(VersionConflictError):
    """循环依赖专用异常"""
    pass

class UndefinedVersionError(VersionConflictError):
    """未定义版本异常"""
    pass

class InvalidVersionSpecError(VersionConflictError):
    """非法版本规范异常"""
    pass

class DependencyResolver:
    """
    三花聚顶 · 依赖解算器
    支持：模块依赖拓扑/循环检测/冲突追踪/日志链路
    """

    def __init__(self):
        self.graph = nx.DiGraph()
        self._sorted_cache = None  # 缓存拓扑排序结果
        logger.info("resolver_initialized")

    def add_module(self, name: str, version: str, deps: Dict[str, str]):
        """
        添加模块及其依赖
        
        Args:
            name: 模块名称
            version: 模块版本号
            deps: 依赖字典 {模块名: 版本约束}
        Raises:
            VersionConflictError: 当检测到版本冲突时
        """
        self._invalidate_cache()
        self.graph.add_node(name, version=str(version))
        logger.info('add_module', extra={
            "module": name, "version": version, "deps": deps
        })

        for dep, spec in deps.items():
            if not self._validate_spec(spec):
                logger.error('invalid_version_spec', extra={
                    "dep": dep, "spec": spec
                })
                raise InvalidVersionSpecError(f"非法版本约束: {spec}")
            if dep not in self.graph.nodes:
                self.graph.add_node(dep, version=None)
            self.graph.add_edge(name, dep)
            try:
                self._check_dep_conflict(name, dep, spec)
            except VersionConflictError as e:
                logger.error('version_conflict', extra={
                    "module": name, "dep": dep, "spec": spec, "error": str(e)
                })
                raise

    def set_module_version(self, name: str, version: str):
        """设置/更新模块版本"""
        self._invalidate_cache()
        if name in self.graph.nodes:
            self.graph.nodes[name]['version'] = str(version)
        else:
            self.graph.add_node(name, version=str(version))
        logger.info('set_module_version', extra={
            "module": name, "version": version
        })

    def _invalidate_cache(self):
        """使缓存失效"""
        self._sorted_cache = None

    def _validate_spec(self, spec: str) -> bool:
        """验证版本约束是否合法"""
        if not spec:
            return True
        try:
            SpecifierSet(spec)
            return True
        except InvalidSpecifier:
            return False

    def _check_dep_conflict(self, module: str, dep: str, spec: str):
        """检查依赖冲突（有冲突就报错）"""
        dep_version = self.graph.nodes[dep]['version']
        if dep_version is None:
            return
        try:
            if not self._is_compatible(spec, dep_version):
                conflict_path = self._get_conflict_path(module, dep)
                msg = (
                    f"版本冲突: {conflict_path}\n"
                    f"需求: {dep}{spec}\n"
                    f"实际: {dep_version}"
                )
                logger.error('dep_version_conflict', extra={
                    "conflict_path": conflict_path,
                    "dep": dep,
                    "spec": spec,
                    "actual": dep_version
                })
                raise VersionConflictError(msg)
        except packaging.version.InvalidVersion:
            logger.error('invalid_dep_version', extra={
                "dep": dep, "version": dep_version
            })
            raise InvalidVersionSpecError(f"非法版本号: {dep_version}")

    def _get_conflict_path(self, module: str, dep: str) -> str:
        """获取冲突路径描述"""
        try:
            path = nx.shortest_path(self.graph, module, dep)
            return "→".join(path)
        except nx.NetworkXNoPath:
            return f"{module}→{dep}"

    def _is_compatible(self, spec: str, actual_version: str) -> bool:
        """检查版本兼容性"""
        if not spec:
            return True
        try:
            return packaging.version.parse(actual_version) in SpecifierSet(spec)
        except (packaging.version.InvalidVersion, InvalidSpecifier):
            logger.error('invalid_version_parse', extra={
                "spec": spec, "version": actual_version
            })
            return False

    def resolve_order(self) -> List[str]:
        """
        解析依赖顺序
        Returns: 排好序的模块列表
        Raises:
            CircularDependencyError: 当存在循环依赖时
            UndefinedVersionError: 当存在未定义版本的模块时
        """
        if self._sorted_cache is not None:
            return self._sorted_cache
            
        try:
            full_order = list(nx.topological_sort(self.graph))
            undefined_deps = self._find_undefined_deps(full_order)
            if undefined_deps:
                logger.error('undefined_module_versions', extra={
                    "modules": list(undefined_deps)
                })
                raise UndefinedVersionError(
                    f"{len(undefined_deps)}个未定义版本的模块: {undefined_deps}"
                )
            self._sorted_cache = [
                m for m in full_order 
                if self.graph.nodes[m]['version'] is not None
            ]
            logger.info('resolve_success', extra={
                "order": self._sorted_cache
            })
            return self._sorted_cache
        except nx.NetworkXUnfeasible:
            cycle = self._find_cycle()
            logger.error('circular_dependency_detected', extra={
                "cycle": cycle
            })
            raise CircularDependencyError(
                f"发现循环依赖: {'→'.join(cycle)}"
            )

    def _find_undefined_deps(self, order: List[str]) -> Set[str]:
        """找出未定义版本的依赖"""
        return {
            m for m in order 
            if self.graph.nodes[m]['version'] is None
        }

    def _find_cycle(self) -> List[str]:
        """尝试找出循环依赖路径"""
        try:
            sccs = list(nx.strongly_connected_components(self.graph))
            for scc in sccs:
                if len(scc) > 1:
                    subgraph = self.graph.subgraph(scc)
                    cycle = list(nx.find_cycle(subgraph))
                    logger.warning('cycle_found', extra={
                        "cycle": cycle
                    })
                    return [u for u, _ in cycle] + [cycle[-1][1]]
            return ["未知循环路径"]
        except Exception as e:
            logger.error('cycle_find_error', extra={
                "error": str(e)
            })
            return ["未知循环路径"]

# 导出
__all__ = [
    "DependencyResolver",
    "VersionConflictError",
    "CircularDependencyError",
    "UndefinedVersionError",
    "InvalidVersionSpecError"
]
