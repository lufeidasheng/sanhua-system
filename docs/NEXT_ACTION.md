# NEXT_ACTION

## 当前主目标
推进“三花聚顶系统总控协作 V2”基础控制面落地，形成可持续的多施工位协作机制。

---

## 当前唯一主工单
- 工单编号：V2-VERIFY-001
- 工单标题：统一最小验证口径
- 所属主链：控制面 / 验证口径
- 主执行位：2号
- 状态：已签收 / 已完成

---

## 本工单目标
1. 固化当前默认最小验证口径
2. 明确 L0 / L1 / L2 验证分层
3. 明确 04 号位标准验证回包格式
4. 本轮不改代码，不切下一张代码工单

---

## 影响文件
- docs/NEXT_ACTION.md
- docs/TECH_DEBT.md
- docs/COORDINATION_FLOW.md

---

## 完成定义（DoD）
- 默认解释器明确为 `./venv/bin/python`
- 默认最低验证明确为 `PYTHONPYCACHEPREFIX=/tmp/pycache ./venv/bin/python -m py_compile <触达文件>`
- `pytest` 仅作为 L1 定向验证候选，不作为强默认
- 不把系统 `python` / `.venv` / GUI 全量启动 / 模型服务 / 音频设备 / `tools` 脚本写成默认验证前提

---

## 本轮状态结论
- `V2-VERIFY-001` 本轮已签收 / 已完成
- 当前最稳定默认口径：
  - `./venv/bin/python` 作为默认解释器
  - `PYTHONPYCACHEPREFIX=/tmp/pycache ./venv/bin/python -m py_compile <触达文件>` 作为默认最低验证
- 验证分层已固化：
  - L0：静态 / 编译级最小验证
  - L1：定向纯测试
  - L2：极小运行态取证
- `pytest` 已有使用痕迹，但 cache 存在失败记录；当前仅作为 L1 条件项，不作为强默认
- 不把系统 `python` / `.venv` / GUI 全量启动 / 模型服务 / 音频设备 / `tools` 脚本写成默认验证前提
- 当前判断：
  - `V2-VERIFY-001` 本轮已完成签收
  - 当前不切新工单，等待总控下一个派工

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
