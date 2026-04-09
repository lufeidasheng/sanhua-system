# NEXT_ACTION

## 当前主线程
- 当前唯一施工工单：
  - 本地运行环境访问边界收口：厘清宿主终端、Codex 执行环境与 localhost 可达性
- 当前目标：
  - 区分哪些执行入口能访问宿主 127.0.0.1:8080
  - 区分代码问题与执行环境权限问题
  - 给出后续最小运行方案
- 当前占用文件：
  - core/core2_0/sanhuatongyu/services/model_engine/register_actions_llamacpp.py
  - entry/cli_entry/cli_entry.py
  - modules/aicore_module/module.py
  - core/core2_0/sanhuatongyu/context_factory.py
- 验收标准：
  - 明确失败发生在哪个执行环境
  - 明确宿主终端 / 当前执行器 / GUI CLI 的访问边界
  - 明确最小可行运行方式
  - 不引入新的聊天主链漂移

## 副线程 A
- desktop_notify / audio_consumer reason 已补齐，后续按需观察是否需要更细语义
- 当前默认不施工

## 副线程 B
- 多模块回答顺序按提问顺序返回
- 当前默认不施工

## 冻结 / 预研池
- music_module native_music_app / Apple Music 后端真实控制
- 自动修复 / 自愈闭环
- 更高效的多 Codex 协作方式继续探索
