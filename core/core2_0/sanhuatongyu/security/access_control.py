# core/core2_0/sanhuatongyu/security/access_control.py

from typing import Dict, List

class AccessControl:
    """
    三花聚顶 · 基于角色的访问控制（RBAC）系统
    - 支持动态角色、权限、事件映射
    - 内建最小权限原则，支持通配符（*）
    """

    def __init__(self):
        # 角色定义：角色名 -> 权限列表（支持*通配符）
        self.roles: Dict[str, List[str]] = {
            "system": ["*"],  # 系统全权
            "admin": ["event.*", "config.*"],
            "module": ["event.publish", "event.subscribe"],
            "user": ["event.subscribe"],
            "guest": [],
        }
        # 事件到权限的映射（事件名 -> 权限标识）
        self.event_permissions: Dict[str, str] = {
            "CONFIG_UPDATE": "config.update",
            "MODULE_LOAD": "module.manage",
            "MODULE_UNLOAD": "module.manage",
            "SYSTEM_SHUTDOWN": "system.control",
            "MODULE_QUERY": "module.query",
        }

    def check_event_permission(self, role: str, event_type: str) -> bool:
        """
        检查角色是否有权限发布指定事件
        :param role: 角色名
        :param event_type: 事件名
        :return: 是否有权限
        """
        required_perm = self.event_permissions.get(event_type)
        if required_perm:
            return self.check_permission(role, required_perm)
        # 未注册事件默认允许（可按需修改）
        return True

    def check_permission(self, role: str, permission: str) -> bool:
        """
        检查角色是否具有指定权限
        :param role: 角色名
        :param permission: 权限名（支持event.*等通配符）
        :return: 是否有权限
        """
        role_perms = self.roles.get(role, [])
        if "*" in role_perms:
            return True
        # 支持 event.* 等模糊匹配
        for perm in role_perms:
            if perm.endswith(".*") and permission.startswith(perm[:-1]):
                return True
            if perm == permission:
                return True
        return False

    def add_role(self, role_name: str, permissions: List[str]):
        """添加新角色及其权限"""
        self.roles[role_name] = permissions

    def grant_permission(self, role: str, permission: str):
        """授予角色新权限"""
        if role not in self.roles:
            self.roles[role] = []
        if permission not in self.roles[role]:
            self.roles[role].append(permission)

    def revoke_permission(self, role: str, permission: str):
        """撤销角色权限"""
        if role in self.roles and permission in self.roles[role]:
            self.roles[role].remove(permission)

    def set_event_permission(self, event: str, permission: str):
        """设置事件所需权限"""
        self.event_permissions[event] = permission

    def remove_event_permission(self, event: str):
        """移除事件权限映射"""
        if event in self.event_permissions:
            del self.event_permissions[event]

    def get_roles(self) -> Dict[str, List[str]]:
        """获取所有角色及权限"""
        return self.roles.copy()

    def get_event_permissions(self) -> Dict[str, str]:
        """获取所有事件权限映射"""
        return self.event_permissions.copy()

# ==== 单元测试 ====
if __name__ == "__main__":
    ac = AccessControl()
    # 基础权限
    assert ac.check_permission("system", "event.publish")
    assert ac.check_permission("admin", "event.subscribe")
    assert ac.check_permission("admin", "event.abc")
    assert not ac.check_permission("user", "config.update")

    # 授权与撤权
    ac.grant_permission("user", "config.update")
    assert ac.check_permission("user", "config.update")
    ac.revoke_permission("user", "config.update")
    assert not ac.check_permission("user", "config.update")

    # 事件权限
    ac.set_event_permission("CUSTOM_EVENT", "custom.handle")
    ac.grant_permission("user", "custom.handle")
    assert ac.check_event_permission("user", "CUSTOM_EVENT")

    print("✅ AccessControl 单元测试通过！")
