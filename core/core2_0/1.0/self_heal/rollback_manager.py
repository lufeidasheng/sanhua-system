import logging
import threading
import os
import shutil
import time
import json
import uuid
from core.core2_0.sanhuatongyu.logger import TraceLogger
log = TraceLogger(__name__)

class RollbackManager:
    def __init__(self, rollback_dir="rollback_snapshots"):
        self.rollback_dir = rollback_dir
        self.lock = threading.RLock()
        self.last_rollback_time = 0
        self.cooldown = 60  # 回滚冷却时间(秒)
        self.rollback_history = []
        self.history_file = os.path.join(rollback_dir, "rollback_history.json")
        
        # 确保快照目录存在
        os.makedirs(self.rollback_dir, exist_ok=True)
        log.info(f"🔄 回滚管理器初始化，快照目录: {self.rollback_dir}")
        
        # 加载已有回滚历史
        self._load_history()

    def _load_history(self):
        """加载并验证回滚历史文件"""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    loaded_history = json.load(f)
                
                # 验证历史记录结构
                valid_history = []
                for item in loaded_history:
                    if all(key in item for key in ["id", "path", "source", "type"]):
                        valid_history.append(item)
                    else:
                        log.warning(f"忽略无效历史记录: {item}")
                
                self.rollback_history = valid_history
                log.info(f"📜 加载 {len(self.rollback_history)} 条回滚历史记录")
            except Exception as e:
                log.error(f"加载回滚历史失败: {e}")
                self.rollback_history = []
        else:
            log.info("未找到历史记录文件，初始化新历史记录")

    def _save_history(self):
        """保存回滚历史到文件"""
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.rollback_history, f, indent=2, ensure_ascii=False)
            log.debug("历史记录保存成功")
        except Exception as e:
            log.error(f"保存回滚历史失败: {e}")

    def can_rollback(self) -> bool:
        """判断是否满足回滚冷却时间"""
        current_time = time.time()
        return (current_time - self.last_rollback_time) > self.cooldown

    def create_snapshot(self, source_path: str, description="", tags=None) -> str:
        """
        创建快照备份指定路径
        :param source_path: 需要备份的路径(文件或目录)
        :param description: 快照描述信息
        :param tags: 快照标签列表
        :return: 快照ID
        """
        if not os.path.exists(source_path):
            log.error(f"创建快照失败：源路径不存在 {source_path}")
            return ""

        # 生成唯一快照ID
        snapshot_id = f"snapshot_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        snapshot_path = os.path.join(self.rollback_dir, snapshot_id)

        try:
            with self.lock:
                # 移除已存在的快照路径
                if os.path.exists(snapshot_path):
                    if os.path.isdir(snapshot_path):
                        shutil.rmtree(snapshot_path)
                    else:
                        os.remove(snapshot_path)
                
                # 根据类型创建快照
                if os.path.isdir(source_path):
                    shutil.copytree(source_path, snapshot_path, symlinks=True)
                    snapshot_type = "dir"
                elif os.path.isfile(source_path):
                    # 确保父目录存在
                    os.makedirs(os.path.dirname(snapshot_path), exist_ok=True)
                    shutil.copy2(source_path, snapshot_path)
                    snapshot_type = "file"
                else:
                    log.error(f"不支持的路径类型: {source_path}")
                    return ""
                
                # 创建快照元数据
                snapshot_info = {
                    "id": snapshot_id,
                    "path": snapshot_path,
                    "source": source_path,
                    "type": snapshot_type,
                    "created_at": time.time(),
                    "description": description,
                    "tags": tags or [],
                    "size": self._get_path_size(snapshot_path),
                }
                
                # 保存历史
                self.rollback_history.append(snapshot_info)
                self._save_history()

                size_mb = snapshot_info["size"] / (1024 * 1024)
                log.info(f"✅ 创建快照成功: {snapshot_id} ({size_mb:.2f} MB)")
                return snapshot_id
        except Exception as e:
            log.error(f"创建快照失败: {e}")
            return ""

    def _get_path_size(self, path):
        """计算路径大小(字节)，递归处理目录"""
        if os.path.isfile(path):
            return os.path.getsize(path)
        if os.path.islink(path):
            return 0  # 不追踪符号链接
        
        total = 0
        try:
            for entry in os.scandir(path):
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat().st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += self._get_path_size(entry.path)
        except Exception as e:
            log.error(f"计算路径大小失败: {e}")
        return total

    def perform_rollback(self, snapshot_id=None) -> bool:
        """
        执行回滚操作
        :param snapshot_id: 指定快照ID(默认最新)
        :return: 是否成功
        """
        if not self.can_rollback():
            remain = self.cooldown - (time.time() - self.last_rollback_time)
            log.warning(f"⏱️ 回滚被阻止，冷却中，还剩 {remain:.1f} 秒")
            return False

        with self.lock:
            if not self.rollback_history:
                log.warning("⚠️ 没有可用回滚快照")
                return False

            # 查找目标快照
            target_snapshot = None
            if snapshot_id:
                for snap in self.rollback_history:
                    if snap["id"] == snapshot_id:
                        target_snapshot = snap
                        break
            else:
                target_snapshot = self.rollback_history[-1]

            if not target_snapshot:
                log.error(f"❌ 未找到指定快照ID: {snapshot_id}")
                return False

            source_path = target_snapshot["source"]
            snapshot_path = target_snapshot["path"]
            snapshot_type = target_snapshot.get("type", "dir")

            # 检查源路径类型是否匹配
            if os.path.exists(source_path):
                if os.path.isdir(source_path) and snapshot_type != "dir":
                    log.error(f"源路径是目录但快照是文件类型，无法回滚")
                    return False
                if os.path.isfile(source_path) and snapshot_type != "file":
                    log.error(f"源路径是文件但快照是目录类型，无法回滚")
                    return False

            try:
                # 创建当前状态备份
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                backup_name = f"backup_{timestamp}_{uuid.uuid4().hex[:6]}"
                
                # 这里安全生成备份路径，避免把目录移动进自己子目录
                if os.path.isfile(source_path):
                    backup_dir = os.path.dirname(source_path)
                    backup_path = os.path.join(backup_dir, backup_name)
                else:
                    # 如果备份目录和源目录冲突，放到rollback_dir的backup子目录
                    backup_dir = os.path.join(self.rollback_dir, "backup")
                    os.makedirs(backup_dir, exist_ok=True)
                    backup_path = os.path.join(backup_dir, backup_name)

                # 移动源目录或文件到备份路径
                if os.path.exists(source_path):
                    shutil.move(source_path, backup_path)
                    log.info(f"📦 备份当前状态到: {backup_path}")

                # 根据类型执行回滚
                if snapshot_type == "dir":
                    shutil.copytree(snapshot_path, source_path, symlinks=True)
                else:  # 文件类型
                    # 确保目标目录存在
                    os.makedirs(os.path.dirname(source_path), exist_ok=True)
                    shutil.copy2(snapshot_path, source_path)

                self.last_rollback_time = time.time()
                log.info(f"✅ 成功回滚到快照: {target_snapshot['id']}")
                return True
            except Exception as e:
                log.error(f"❌ 回滚失败: {e}")
                # 尝试恢复备份
                if os.path.exists(backup_path):
                    try:
                        if os.path.exists(source_path):
                            if os.path.isdir(source_path):
                                shutil.rmtree(source_path)
                            else:
                                os.remove(source_path)
                        shutil.move(backup_path, source_path)
                        log.info("🔄 已恢复回滚前的备份")
                    except Exception as re:
                        log.error(f"备份恢复失败: {re}")
                return False

    def rollback_last_action(self) -> bool:
        """回滚到最新快照"""
        return self.perform_rollback()

    def get_snapshot_list(self):
        """获取快照列表拷贝"""
        with self.lock:
            return [s.copy() for s in self.rollback_history]

    def cleanup_old_snapshots(self, max_count=10, max_age_days=30) -> int:
        """
        清理旧快照
        :param max_count: 最大保留数量
        :param max_age_days: 最大保留天数
        :return: 删除数量
        """
        with self.lock:
            current_time = time.time()
            # 按创建时间排序(最新在前)
            sorted_snapshots = sorted(
                self.rollback_history, 
                key=lambda x: x["created_at"], 
                reverse=True
            )
            
            to_delete = []
            kept_count = 0
            
            for snap in sorted_snapshots:
                # 优先保留最近的 max_count 个
                if kept_count < max_count:
                    kept_count += 1
                    continue
                
                # 检查是否超过最大天数
                age_days = (current_time - snap["created_at"]) / 86400
                if age_days > max_age_days:
                    to_delete.append(snap)
            
            # 删除快照
            for snap in to_delete:
                try:
                    if os.path.exists(snap["path"]):
                        if os.path.isdir(snap["path"]):
                            shutil.rmtree(snap["path"])
                        else:
                            os.remove(snap["path"])
                    self.rollback_history.remove(snap)
                    log.info(f"🗑️ 删除旧快照: {snap['id']}")
                except Exception as e:
                    log.error(f"删除快照失败 {snap['id']}: {e}")
            
            if to_delete:
                self._save_history()
            
            return len(to_delete)
