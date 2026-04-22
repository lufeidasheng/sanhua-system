# NEXT_ACTION

## 当前主目标
推进“三花聚顶系统总控协作 V2”基础控制面落地，形成可持续的多施工位协作机制。

---

## 当前唯一主工单
- 工单编号：V2-HEALTH-001
- 工单标题：统一健康读取主链与 metrics 消费契约
- 所属主链：健康主链 / metrics 契约
- 主执行位：1号
- 状态：已签收 / 已完成

---

## 本工单目标
1. 收口 `main_controller.py` 健康读取主链到真实模块路径与 `get_system_health()`
2. 收口 metrics 消费契约
3. 确保非完整 metrics 输入受控降级
4. 本轮完成后不预切下一票，进入候选扫描阶段

---

## 影响文件
- `main_controller.py`

---

## 完成定义（DoD）
- `main_controller.py` 健康读取口径已统一到真实模块路径与 `get_system_health()`
- 裸导入与错误读取调用已移除
- metrics 契约已被主循环阈值逻辑正确消费
- `metrics=None` / 非 list / 缺字段 已受控降级
- 环境噪音 `psutil` 架构问题与 `daemon` 模块缺失不计入本票拒签理由
- 本轮不扩大解释为 `system.health_check` 主链、GUI、chat、dispatcher、AICore、memory、modules 已重构

---

## 本轮状态结论
- `V2-HEALTH-001` 已签收 / 已完成
- 本轮签收口径仅限：
  - `main_controller.py` 健康读取口径已统一到真实模块路径与 `get_system_health()`
  - metrics 消费契约已收口
  - 非完整 metrics 输入已受控降级
- 控制面约束：
  - 当前无活动主施工票
  - 已进入下一张唯一主工单候选扫描阶段
- 本轮不扩大解释为 `system.health_check` 主链、GUI、chat、dispatcher、AICore、memory、modules 已重构
- 当前判断：
  - `V2-HEALTH-001` 状态为已签收 / 已完成
  - 当前不切下一张工单

---

## V2-BOOT-001 收口状态
- 工单编号：V2-BOOT-001
- 工单标题：总控协作 V2 控制面基线落库
- 状态：已完成 / 已收口
- 收口结论：
  - `AGENTS.md` 已作为当前正式协作边界文件口径
  - `docs/COORDINATION_FLOW.md` 已固化“1 个 GPT 总控 + 4 个 Codex 工位”协作模式
  - `docs/NEXT_ACTION.md` 已完成切单机制与下一张唯一代码工单定义
  - `docs/TECH_DEBT.md` 已具备最小可用台账能力

---

## 正式切单记录
- 收口确认人：总控
- 02号位职责：回填收口条件与保持控制面一致性，不负责最终拍板
- 正式切单结果：
  - `V2-BOOT-001` 已由总控确认收口完成
  - 当前唯一主工单已正式切换为 `V2-DISPATCH-001`
  - `V2-DISPATCH-001` 已标记为 01 号位当前唯一代码工单

---

## 历史工单记录：V2-DISPATCH-001
- 工单编号：V2-DISPATCH-001
- 工单标题：统一 `context.call_action / dispatcher.execute` 调用口径并补最小验证
- 所属主链：动作路由稳定 / 统一调度主链
- 主执行位：1号
- 历史状态：已完成 / 已签收
- 当前代码事实：
  - 当前 live 主链不是 `dispatch_action`
  - 当前 live 主链是 `context.call_action() -> dispatcher.execute()`
  - `ACTION_MANAGER` 当前真身是 `core/core2_0/sanhuatongyu/action_dispatcher.py` 中 dispatcher 的别名
  - `dispatch_action` 仅剩文档 / 工具兼容语义，不作为当前 live 主链目标
- 当前目标：
  - 统一 live 主链口径到 `context.call_action() -> dispatcher.execute()`
  - 收敛围绕 `ACTION_MANAGER` / dispatcher 的别名与桥接使用方式
  - 为 01 号位补一张可直接执行、可验证的最小代码工单
- 边界：
  - 聚焦 live 主链文件与最小验证
  - 不扩成 GUI 全量重构
  - 不触达 legacy / 模块中文副本 / `core/core2_0/1.0/`
  - 不触达 `tools` / scaffold / 各类备份与 patch 噪音树
- 最小验证方式：
  - 明确 `context.call_action()` 与 `dispatcher.execute()` 的真实入口关系
  - 明确 `ACTION_MANAGER` 与 dispatcher 的别名关系
  - 明确 `dispatch_action` 是否仅保留兼容语义
  - 给出最小验证命令与结果回填格式
- DoD：
  - live 主链调用口径明确
  - `context.call_action() -> dispatcher.execute()` 被写成唯一主口径
  - `ACTION_MANAGER` / dispatcher / `dispatch_action` 的角色边界写清
  - 01 号位可按该条目直接开做最小代码工单
