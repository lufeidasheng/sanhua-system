# TECH_DEBT

## 使用规则
1. 发现问题先登记，再决定是否当前修
2. 技术债描述要短、准、可追踪
3. 修复后必须回填状态和验证结果

---

## 当前技术债

### TD-001
- 标题：GUI 仍承担过多系统编排职责
- 等级：高
- 范围：`entry/gui_entry/gui_main.py`
- 现象：
  - 存在预路由、记忆短路、AICore 桥接、alias 强制加载等职责堆叠
- 影响：
  - GUI 不再只是 Shell，系统真相源边界模糊
- 建议：
  - 继续剥离到统一总控/桥接层

---

### TD-002
- 标题：动作调用链仍需统一口径
- 等级：高
- 范围：AICore / Dispatcher / GUI Bridge
- 现象：
  - 历史文档中曾将 `dispatch_action / call_action` 并列写成主调用口
  - 当前真实口径已收敛为 `context.call_action(...)` 主入口
- 影响：
  - 调试难、追踪难、验收难
- 建议：
  - 统一以 `context.call_action(...)` 为主入口
  - `dispatcher.call_action / execute` 作为调度桥 / 执行面
  - `dispatch_action` 仅保留兼容语义

---

### TD-005
- 标题：默认验证口径需持续保持一致
- 等级：中
- 范围：全局协作流程
- 现象：
  - 验证命令容易混用系统 `python`、`.venv`、GUI 全量启动、模型服务、音频设备或 `tools` 脚本
  - `pytest` 已有使用痕迹，但 cache 存在失败记录
- 影响：
  - 容易把环境差异误判为代码回归
- 建议：
  - 默认解释器为 `./venv/bin/python`
  - 默认最低验证为 `PYTHONPYCACHEPREFIX=/tmp/pycache ./venv/bin/python -m py_compile ...`
  - `pytest` 目前只属于 L1 条件项，不是强默认
  - 不把系统 `python` / `.venv` / GUI 全量启动 / 模型服务 / 音频设备写成默认前提

---

### TD-003
- 标题：仓库资产噪音需按 mainline 净化口径判断
- 等级：中
- 范围：仓库资产 / 测评边界 / 风险归因
- 现象：
  - `V2-ASSET-001` / `V2-ASSET-002` / `V2-ASSESS-002` 已形成闭环：
    - 资产三层边界已定版
    - 分类证据已输出
    - 默认测评已切到 `scan_mode=mainline`
  - 当前资产证据源：`reports/repo_assets/repo_asset_map.json`
  - 当前净化报告源：`reports/system_assessment/latest/system_report.md`
  - 当前净化结果：
    - 纳入资产：401
    - 排除资产：1738
    - Python 文件：207
    - 风险项：9
    - mainline blocker：9
- 影响：
  - 如果跳过 mainline 净化口径，vendor / runtime / legacy / unknown 噪音会被误判为三花主链 blocker
  - `full scan` 发现不能直接升级为当前主链 blocker
  - 9 个 `mainline blocker` 只能作为当前主链风险池 / 当前主链 blocker 候选，不等价于全部必须立即施工
- 建议：
  - 后续施工只基于净化报告中的 GUI 边界热点、过大主链文件、运行态真相深采集继续收敛
  - 灰区目录继续按文件与引用关系复核
  - 当前不做物理搬仓
  - 当前不做全仓质量审计
  - 当前不把模型资产 / venv / logs / legacy 当作主链施工对象
  - 不把 `unknown` 视为失败

---

### TD-004
- 标题：验证证据与工单结果回填还未形成强约束
- 等级：中
- 范围：全局协作流程
- 现象：
  - 容易出现“改了但没证据”
- 影响：
  - 验收质量波动
- 建议：
  - 让 4号验证位标准化输出日志、命令、结果摘要

---

### TD-006
- 标题：`psutil` 二进制架构与当前环境不匹配
- 等级：中
- 范围：本地验证环境
- 现象：
  - 运行验证中存在 `psutil` 架构不匹配噪音
- 影响：
  - 容易把环境问题误判为主链代码故障
- 建议：
  - 统一校正当前解释器与 `psutil` 二进制架构

---

### TD-007
- 标题：`python-daemon` 依赖缺失
- 等级：中
- 范围：本地验证环境
- 现象：
  - 当前环境缺少 `daemon` 模块
- 影响：
  - 部分验证路径会因依赖缺失受阻
- 建议：
  - 为当前标准验证环境补齐 `python-daemon` 依赖
