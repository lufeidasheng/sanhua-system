# 测评范围策略

## 主链视角

后续测评默认采用主链视角：先判断资产是否参与当前主链运行、测评或派工，再决定是否计入三花主链 blocker。

目录归属是一级过滤规则，不是最终定责规则。凡是没有 live 主链显式引用证据的 Vendor / External 与 Runtime / Legacy 问题，默认不计入三花主链 blocker。

## Mainline 默认白名单原则

默认纳入主链测评的资产：

- `core/`
- `entry/`
- `modules/`
- 被当前启动链或调度链真实读取的 `config/` 文件
- `docs/` 中控制面与治理文档
- 当前工单明确点名的主链治理测试

白名单使用规则：

- mainline scan 默认只扫白名单与当前工单点名文件。
- 如果发现白名单外资产被 live 主链显式 import、执行、读取或被配置引用，可以把该引用点列入人工复核。
- 不因一次引用把整个外部目录、历史目录或运行目录升级为 Mainline。

## 默认排除黑名单原则

默认排除主链 blocker 计算的资产：

- `_legacy_disabled/`
- `legacy/`
- `_audit*`
- `rollback_snapshots/`
- `llama.cpp/`
- `juyuan_models/`
- `models/`
- `piper-master/`
- `ollama_*`
- `third_party/`
- `deps/`
- `dependencies/`
- `external/`
- `venv/`
- `.venv/`
- `logs/`
- `runtime/`
- `cache/`
- `tmp/`
- `recordings/`
- 运行态数据、历史备份、压缩包、安装包、回滚快照、日志和缓存

明确规则：

- `_legacy_disabled` 默认不计入三花主链 blocker，除非有 live 主链显式引用证据。
- `llama.cpp` 默认不计入三花主链 blocker，除非当前工单切到依赖层或运行环境治理。
- `juyuan_models` 默认不计入三花主链 blocker，除非当前工单切到模型资产治理。
- `venv/.venv` 默认不计入三花主链 blocker，除非当前工单切到环境治理。
- `logs/runtime/cache/tmp` 默认不计入三花主链 blocker，除非有 live 主链显式引用证据或当前工单需要运行态取证。

## 灰区目录人工复核原则

灰区目录不能整体纳入或整体排除，必须按文件与引用关系复核。

灰区目录：

- `tools/`
- `docs/`
- `config/`
- `tests/`
- `scripts/`
- `scaffold/`
- `data/memory/`

复核规则：

- `tools/` 默认不进 Mainline；只有被当前工单点名，或被主链验证实际使用的单个脚本，才临时纳入。
- `docs/` 只纳入控制面与治理文档；压缩包、导出物、缓存不纳入。
- `config/` 只纳入被启动链或调度链真实读取的配置；生成物和缓存不纳入。
- `tests/` 只纳入当前主链治理测试或工单点名测试；不把全量测试失败直接计入本轮主链 blocker。
- `scripts/` 默认按运行辅助处理；只有被当前工单点名或验证命令实际使用时才纳入。
- `scaffold/` 默认按脚手架或历史辅助处理，不作为主链真相源。
- `data/memory/` 可作为运行态取证来源，不作为代码测评对象；历史备份和 `.bak` 不纳入 blocker。

## mainline scan 与 full scan

mainline scan 适用场景：

- 主链稳定性验收
- 当前施工工单验收
- 总控判断是否存在三花主链 blocker
- 04 号位正式取证

mainline scan 范围：

- Mainline 白名单
- 当前工单明确点名文件
- 灰区目录中被当前工单点名或被验证命令实际使用的单个文件
- 白名单外但存在 live 主链显式引用证据的具体引用点

full scan 适用场景：

- 仓库资产治理
- 依赖层治理
- 历史资产盘点
- 模型资产盘点
- 环境与运行产物治理

full scan 规则：

- full scan 的发现默认只作为资产治理线索。
- full scan 发现不得直接升级为三花主链 blocker。
- 若 full scan 发现与 live 主链存在显式引用关系，必须回到 mainline scan 规则下复核引用点。

## blocker 判定

计入三花主链 blocker 必须满足至少一个条件：

- 影响当前 Mainline 白名单内代码或配置的启动、调度、路由、状态协议、主链测试。
- 被当前工单明确点名为施工或验收对象。
- 存在 live 主链显式 import、执行命令、配置读取或运行调用证据。
- 被 mainline scan 定位为当前主链可复现故障点。

不计入三花主链 blocker 的情况：

- 仅存在于 Vendor / External 目录内，且没有 live 主链显式引用证据。
- 仅存在于 Runtime / Legacy 目录内，且没有 live 主链显式引用证据。
- 仅由 full scan 发现，但未通过 mainline scan 复核。
- 仅影响历史脚本、冻结资产、日志、缓存、虚拟环境或模型大文件。
