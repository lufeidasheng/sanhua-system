# 技术债台账

说明：
- 发现问题时先记简版
- 修复后回填状态、验证命令、验证结果
- 非本工单问题只记录，不顺手扩修
- 每条债务必须挂到某条主线或能力域

控制面约束：
- 当前所有工单默认服务于“三花聚顶本地稳定版 v1 / 贾维斯本地内核雏形”
- 不再按散功能思路推进，优先主链闭环、owner 收口、状态真相源、聚感表达
- 高风险家居/实体世界控制默认后置，未进入当前阶段主施工范围

## T001 - music_module 真实播放闭环未验收
- 类型：模块实现
- 状态：已解决
- 影响等级：中
- 是否阻塞主链：否
- 所属主线：音乐能力 / 本地稳定版 v1
- 相关文件：
  - modules/music_module/module.py
- 修复摘要：
  - play_music owner 已从 aicore 收口到 music_module
  - stop_music / pause_music 已收口到 music_module
  - GUI 返回真实业务文案，不再返回状态码 1
  - macOS 下 Music.app 未进入播放态时可自动回退本地播放
  - 已实现 active backend / track / process 状态记录
  - 本地 fallback 已实现按真实活跃后端停播，并在停播后清空 active state
  - play_music_action 已支持 filepath/path/file 显式文件播放
- 验证命令：
  - GUI 真实启动后输入：“播放音乐”
  - GUI 真实启动后输入：“停止播放”
  - ctx.call_action("play_music", {"filepath": "/System/Library/Sounds/Glass.aiff"})
- 验证结果：
  - live GUI 下 play_music / stop_music 已由 music_module 接管
  - GUI 不再返回状态码 1，而是返回真实业务文案
  - Music.app 未进入播放态时会回退到本地播放
  - active backend / track / process 可随真实播放态更新
  - 本地 fallback 可被 stop_music 真实停播
  - 返回 “🎶 正在播放: Glass.aiff”
  - music 播放闭环通过

## T002 - desktop_notify 缺少 macOS 原生通知后端
- 类型：模块实现
- 状态：已缓解
- 影响等级：低
- 是否阻塞主链：否
- 所属主线：聚感可处置 / 本地稳定版 v1
- 相关文件：
  - modules/desktop_notify/module.py
- 当前现象：
  - 当前 reason = backend_stdout_fallback
  - 可降级到 stdout，不阻塞主链
- 下一步最小工单：
  - 评估并接入 macOS 可用的原生通知后端

## T003 - audio_capture macOS spawn/pickle 兼容问题
- 类型：模块实现
- 状态：已缓解
- 影响等级：中
- 是否阻塞主链：否
- 所属主线：聚感可处置 / 音频链路
- 相关文件：
  - modules/audio_capture/module.py
- 当前现象：
  - reason = spawn_pickle_thread_local
  - 当前采用已知降级策略，不阻塞主链
- 下一步最小工单：
  - 评估无子进程模式或兼容输入方案

## T004 - 多模块回答顺序未按提问顺序返回
- 类型：体验层
- 状态：待处理
- 影响等级：低
- 是否阻塞主链：否
- 所属主线：体验收口
- 相关文件：
  - core/gui_bridge/chat_orchestrator.py
- 当前现象：
  - 多模块问答时输出顺序可能不按用户提问顺序
- 下一步最小工单：
  - 按用户提问顺序排列命中模块后再输出

## T005 - music_module native_music_app 仅为候选骨架，未接真实控制
- 类型：架构预研
- 状态：待处理
- 影响等级：中
- 是否阻塞主链：否
- 所属主线：平台自适应后端 / 音乐能力
- 相关文件：
  - modules/music_module/module.py
- 当前现象：
  - backend_candidates 已出现 native_music_app
  - 但当前仅为候选占位，未接入真实 Apple Music / Music.app 控制
- 下一步最小工单：
  - 设计并接入 macOS 原生音乐控制后端的最小动作骨架

## T006 - 自然语言“播放音乐”未稳定直达音乐动作
- 类型：主链体验
- 状态：已解决
- 影响等级：中
- 是否阻塞主链：否
- 所属主线：意图路由 / 体验收口
- 相关文件：
  - alias / intent / chat route 相关链路
- 修复摘要：
  - sanhuatongyu.logger 已补齐 TraceLogger 兼容导出
  - GUI alias 启动链假阴性已修复，不再把已注册 alias 误判为未加载
  - “播放音乐”这类自然语言输入已可稳定直达音乐动作链
- 验证命令：
  - GUI 真实启动后输入：“播放音乐”
- 验证结果：
  - GUI 启动时 aliases 可正常加载
  - “播放音乐”不再先走 ai.chat
  - 自然语言直达音乐动作验收通过

## T007 - core/core2_0/1.0 旧式 TraceLogger 导入链仍残留
- 类型：兼容治理
- 状态：待处理
- 影响等级：中
- 是否阻塞主链：否
- 所属主线：历史兼容收口 / 本地稳定版 v1
- 相关文件：
  - core/core2_0/1.0/security_manager.py
  - core/core2_0/1.0/utils.py
  - core/core2_0/1.0/self_heal/log_analyzer.py
  - core/core2_0/1.0/self_heal/rollback_manager.py
  - core/core2_0/1.0/self_heal/self_healing_scheduler.py
- 当前现象：
  - sanhuatongyu.logger 虽已补 TraceLogger 兼容导出
  - 但 1.0 历史链仍直接 import TraceLogger
  - 后续 logger 体系再收口时仍有回归风险
- 下一步最小工单：
  - 将上述历史导入点统一收敛到 get_logger 或当前官方 logger 接口

## T014 - CLI 入口存在广义异常静默吞掉问题
- 类型：运行面可观测性
- 状态：已解决
- 影响等级：中
- 是否阻塞主链：否
- 所属主线：入口稳定性 / 本地稳定版 v1
- 相关文件：
  - entry/cli_entry/cli_entry.py
- 修复摘要：
  - entry/cli_entry/cli_entry.py 中两处 except Exception: pass 已改为 stderr 最小日志输出
  - 保留原有 CLI 主流程结构，不扩改入口链
- 验证命令：
  - python3 entry/cli_entry/cli_entry.py
  - 触发 CLI 入口异常路径，观察 stderr
- 验证结果：
  - CLI 入口不再静默吞掉异常
  - 异常路径可输出最小可观测日志
  - 未引入新的 CLI 启动错误

## T015 - system_control 的 Linux xdg-open 依赖缺少平台能力探测
- 类型：平台适配
- 状态：待处理
- 影响等级：中
- 是否阻塞主链：否
- 所属主线：平台自适应后端 / 系统控制
- 相关文件：
  - core/system/system_control.py
- 当前现象：
  - 当前直接使用 xdg-open 打开 URL / 文件 / 目录
  - 缺少更明确的平台能力探测、reason 与降级语义
  - 在跨平台或裁剪环境下存在行为不透明风险
- 下一步最小工单：
  - 为 xdg-open 链路补平台探测与失败 reason，明确 Linux 打开动作的处置语义

## T016 - AICore 职责混杂，意图识别与动作路由归属待收口
- 类型：架构收口
- 状态：已部分解决
- 影响等级：高
- 是否阻塞主链：否
- 所属主线：AICore 职责收口 / 本地稳定版 v1
- 相关文件：
  - core/aicore/intent_action_generator.py
  - core/core2_0/sanhuatongyu/intent
  - core/core2_0/sanhuatongyu/action_dispatcher.py
  - core/aicore/command_router.py
  - core/aicore/action_manager.py
- 修复摘要：
  - IntentRecognizer 主归属已从 core/aicore/intent_action_generator 迁到 core/core2_0/sanhuatongyu/intent
  - action_dispatcher.py 已切到新路径导入
  - 旧路径 shim 仍可导入，兼容未断
- 验证命令：
  - 导入级运行验证：NEW_OK
  - 导入级运行验证：OLD_SHIM_OK
  - 导入级运行验证：DISPATCHER_OK
- 验证结果：
  - 新路径导入成功
  - 旧路径 shim 导入成功
  - action_dispatcher 已可从新归属路径工作
  - IntentRecognizer 收口阶段性完成
  - command_router 审计已完成，当前未进入主运行链，属于历史残留 / 低优先级迁移对象
  - ActionSynthesizer / IntentRegistry 审计已完成，当前未进入主运行链，属于未挂载能力 / 历史预研模块
  - action_manager.py 仍是 live 运行链动作注入入口
  - 当前存在 owner 重叠 / 后覆盖 / 风险元信息不一致问题
  - 第一批 system_control 5 动作前置补口已完成
  - shutdown / reboot / lock_screen / suspend / logout 已由 system_control 同名注册
  - ActionMapper 对上述 5 个动作的第一批让权保护已完成
  - 若现有 owner 来自 system_control，ActionMapper 会跳过注册
  - live owner 验证已通过
  - 上述 5 个动作的 owner 均为 system_control
  - 上述 5 个动作的 func 均为 SystemControlModule.action_*
  - 第一批让权保护已完整闭环
  - 第二批候选动作已收敛为：turn_off_display / screenshot / open_url / open_browser / check_network
  - 第二批试点 turn_off_display / screenshot 前置补口已完成
  - turn_off_display 与 screenshot 已由 system_control 同名注册
  - 第二批试点让权保护已完成
  - turn_off_display | owner=system_control | func=SystemControlModule.action_turn_off_display
  - screenshot | owner=system_control | func=SystemControlModule.action_screenshot
  - 第二批试点 live owner 验证已通过
  - 第二批试点已完整闭环
  - open_url 前置补口已完成
  - open_url 已由 system_control 同名注册
  - open_url 让权保护已完成
  - open_url | owner=system_control | func=SystemControlModule.action_open_url
  - open_url live owner 验证已通过
  - 第三批单动作试点 open_url 已完整闭环
  - ai.chat 主桥统一注册入口已完成
  - GUI 的 ai.chat 导入即注册副作用职责已移除
  - chat_orchestrator 已在 ai.chat 第一跳前惰性 ensure 注册
  - CLI/GUI 主桥口径已对齐到实施态
  - CLI 已统一为 ai.chat -> aicore.chat -> AICore.chat 顺序
  - aicore.chat 已收紧为兼容 / 兜底桥语义
  - ai.chat 主桥实施的语法级编译检查已通过
  - ai.chat ensure 注册已验证通过
  - GUI orchestrator 第一跳先命中 ai.chat 已验证通过
  - aicore.chat 当前已处于兼容 / 兜底桥语义
  - CLI 主桥失桥修复已完成
  - SystemContext.call_action 标准接口已补齐
  - CLI 已能先走 ai.chat
  - aicore.chat 已落在兼容 / 兜底位置
  - AICore.chat 递归问题修复已完成
  - aicore.chat 兼容桥自指回环已切断
  - CLI 链路中不再出现 maximum recursion depth exceeded
  - ai.chat 正式主桥与 aicore.chat 兼容桥语义未漂移
  - ai.chat 后端连接失败定位已完成
  - llama-server 已确认在 127.0.0.1:8080 监听
  - base_url 解析结果正确，当前仍为 http://127.0.0.1:8080/v1
  - 当前阻塞点位于运行环境 / 权限边界，而不是聊天主链代码
  - 当前执行环境访问 127.0.0.1:8080 会报 Operation not permitted
  - GUI 真机验证受 PyQt6 架构环境阻塞
- 下一步最小工单：
  - 厘清宿主终端、Codex 执行环境与 GUI / CLI 对 localhost 的访问边界，并给出最小可行运行方式
