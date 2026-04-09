# 聚核助手 (JUHE Assistant)

## 简介

聚核助手是一款基于Python和深度学习模型的本地智能助理，集成了自然语言处理、语音合成、本地音乐播放和系统监控等功能。  
设计目标是轻量、开源、可本地部署，帮助用户实现多场景智能交互。

## 主要功能

- 多模型支持（本地 ChatGLM、远程 Llama3 等）
- 自然语言对话，支持中文
- 本地音乐随机播放
- 系统资源监控与告警
- 语音合成与播放（基于微软 Edge TTS）
- 模块化设计，易于扩展

## 项目结构

聚核助手/
├── run.py               # 启动入口脚本
├── requirements.txt     # 依赖列表
├── aicore/              # AI核心模块
├── modules/             # 功能模块
├── system/              # 系统控制和监控模块
├── aicore/             # AI记忆管理模块
├── data/                # 数据存储
├── assets/              # 资源文件（音频、图片等）
├── gui/                 # 图形界面模块
└── README.md            # 项目说明文件

## 安装

1. 克隆代码库：

git clone <你的代码库地址>
cd 聚核助手

2. 安装依赖：

pip install -r requirements.txt

3. 确保系统已安装 mpv（音频播放器）：

# Fedora
sudo dnf install mpv

# Ubuntu/Debian
sudo apt install mpv

## 运行

python run.py

## GUI 启动（默认推荐）

- 默认推荐 GUI 启动方式：`./run_gui.sh`
- 正式 GUI 主入口：`entry/gui_entry/gui_main.py`

## 未来计划

- 支持更多本地AI模型  
- 支持多平台图形界面（Linux, Windows, macOS）  
- 增强语音交互能力  
- 增加插件系统支持

## 贡献

欢迎提交 issue 和 PR，帮助改进聚核助手！

## 联系方式

开发者:lufei
邮箱: 1378483183@qq.com
