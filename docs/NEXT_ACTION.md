# NEXT_ACTION

## 当前主目标
推进“三花聚顶系统总控协作 V2”基础控制面落地，形成可持续的多施工位协作机制。

---

## 当前唯一主工单
- 工单编号：V2-BOOT-001
- 工单标题：总控协作 V2 控制面基线落库
- 所属主链：总控协作 / 工单治理 / 控制面
- 主执行位：2号（记录/回填位）
- 状态：进行中

---

## 本工单目标
1. 固化 AGENTS 协作规则
2. 固化 COORDINATION_FLOW 协作流
3. 初始化 NEXT_ACTION / TECH_DEBT 控制面
4. 为 1号主施工位准备下一张真正代码工单

---

## 影响文件
- AGENTS.md
- docs/COORDINATION_FLOW.md
- docs/NEXT_ACTION.md
- docs/TECH_DEBT.md

---

## 完成定义（DoD）
- 控制面文件已存在且内容可用
- 角色分工清晰
- 工单流转规则清晰
- 下一张主施工工单可直接开做

---

## 下一张候选工单
### 候选 A
- 工单编号：V2-CORE-001
- 标题：GUI Shell 边界再收敛，继续剥离非显示职责
- 主执行位：1号

### 候选 B
- 工单编号：V2-DISPATCH-001
- 标题：统一 dispatch_action / call_action 调用口径并补最小验证
- 主执行位：1号

### 候选 C
- 工单编号：V2-MEM-001
- 标题：记忆写回链路与 PromptMemoryBridge 边界复核
- 主执行位：1号

---

## 当前建议
优先开：
`V2-DISPATCH-001`

原因：
- 它是总控闭环最核心的骨架之一
- 能直接提升“系统统一调度”能力
- 后续 GUI / Memory / Module 接入都会受益