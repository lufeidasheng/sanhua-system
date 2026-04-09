import os, re, sys, io

# 1) 找 GUI 文件（优先你的融合版，否则回落到旧入口）
candidates = [
    "tools/gui_fusion_pro.py",
    "entry/gui_entry/gui_main.py",
]
target = next((p for p in candidates if os.path.exists(p)), None)
if not target:
    print("❌ 没找到 GUI 文件：", candidates); sys.exit(1)

code = io.open(target, "r", encoding="utf-8").read()
orig = code

# 2) 顶部插入：engine_compat.install() + 注册 ai.* 动作（若未存在）
if "engine_compat import install" not in code:
    hook = (
        "\n# ==== 模型后端动作注册（llama.cpp HTTP） ====\n"
        "try:\n"
        "    from core.core2_0.sanhuatongyu.services.model_engine.engine_compat import install\n"
        "    install()\n"
        "    import core.core2_0.sanhuatongyu.services.model_engine.register_actions_llamacpp  # noqa: F401\n"
        "except Exception as _e:\n"
        "    print(f\"[GUI] ai.* 动作注册失败: {_e}\")\n"
    )
    # 尝试插到 imports 之后
    m = re.search(r"from PyQt6[^\n]+\n", code)
    if m:
        code = code[:m.end()] + hook + code[m.end():]
    else:
        code = hook + code

# 3) 将 MainWindow.handle_user_message 改为：优先走 ai.chat, 失败再走 AICore/aicore.chat
pat = re.compile(r"def\s+handle_user_message\s*\(\s*self\s*,\s*text\s*:\s*str\s*\)\s*:(.*?)(?=\nclass|\n# =|def\s)", re.S)
def repl(m):
    return (
        "def handle_user_message(self, text:str):\n"
        "    self.append_log(f\"🧑‍💻 用户: {text}\")\n"
        "    self.chain.show_chain_chat(text)\n"
        "    reply = \"\"\n"
        "    # 1) 优先调度器 ai.chat（直连 llama.cpp HTTP）\n"
        "    try:\n"
        "        res = self._safe_call_action(\"ai.chat\", {\"text\": text, \"system\": \"你是三花聚顶·聚核助手\"})\n"
        "        if isinstance(res, dict):\n"
        "            reply = (res.get(\"data\") or {}).get(\"reply\") or res.get(\"reply\") or \"\"\n"
        "        elif isinstance(res, str):\n"
        "            reply = res\n"
        "    except Exception as e:\n"
        "        self.append_log(f\"⚠️ ai.chat 失败：{e}\")\n"
        "    # 2) AICore 直连兜底\n"
        "    if not reply and getattr(self, 'ac', None):\n"
        "        try:\n"
        "            reply = self.ac.chat(text) or \"\"\n"
        "        except Exception as e:\n"
        "            self.append_log(f\"⚠️ AICore.chat 失败：{e}\")\n"
        "    # 3) 再兜底 aicore.chat 动作（演示环境或其他实现）\n"
        "    if not reply:\n"
        "        try:\n"
        "            res = self._safe_call_action(\"aicore.chat\", {\"query\": text})\n"
        "            reply = (res or {}).get(\"response\") if isinstance(res, dict) else (res or \"\")\n"
        "        except Exception as e:\n"
        "            reply = f\"AI 异常：{e}\"\n"
        "    if not reply:\n"
        "        reply = \"（无回复）\"\n"
        "    self.chat_panel.add_bubble(reply, False)\n"
        "    self.append_log(f\"🤖 AI: {reply}\")\n"
        "    if getattr(self, 'tts_enabled', False):\n"
        "        try:\n"
        "            acts = self._list_actions()\n"
        "            if any(a.get('name')=='tts.speak' for a in acts):\n"
        "                self._safe_call_action('tts.speak', {'text': reply, 'lang': 'zh'})\n"
        "                self.append_log('🔊 [TTS] 已自动播报')\n"
        "        except Exception as e:\n"
        "            self.append_log(f\"❌ TTS失败: {e}\")\n"
    )
code = pat.sub(repl, code)

if code != orig:
    io.open(target, "w", encoding="utf-8").write(code)
    print(f"✅ GUI 已打补丁：{target}")
else:
    print(f"ℹ️ GUI 无需变更：{target}")
