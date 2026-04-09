#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
from datetime import datetime
import shutil
import sys


TARGET = Path("core/aicore/extensible_aicore.py")


def backup_file(path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path.with_name(path.name + f".bak.{ts}")
    shutil.copy2(path, bak)
    return bak


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"未找到可替换片段: {label}")
    return text.replace(old, new, 1)


def main() -> None:
    if not TARGET.exists():
        print(f"❌ 未找到文件: {TARGET}")
        sys.exit(1)

    bak = backup_file(TARGET)
    print(f"==> 已备份: {bak}")

    text = TARGET.read_text(encoding="utf-8")

    old_block = """            if self._should_store_assistant_message(resp_text):
                self.record_chat_memory("assistant", resp_text)
            else:
                log.info("assistant 输出未写入记忆：质量门禁未通过")

            self.record_action_memory(
                action_name="aicore.chat",
                status="success",
                result_summary="后端调用成功",
            )

            return resp_text
"""

    new_block = """            if self._should_store_assistant_message(resp_text):
                self.record_chat_memory("assistant", resp_text)

                self.record_action_memory(
                    action_name="aicore.chat",
                    status="success",
                    result_summary="后端调用成功",
                )
                return resp_text
            else:
                log.info("assistant 输出未写入记忆：质量门禁未通过")
                self.record_action_memory(
                    action_name="aicore.chat",
                    status="degraded",
                    result_summary="回答未通过工程真实性门禁，已阻止对外直接返回",
                )
                return (
                    "⚠️ 当前模型回答未通过工程真实性校验，已阻止直接返回与写入记忆。\\n\\n"
                    "建议改用以下方式继续：\\n"
                    "1. 运行 debug_memory_prompt / debug_assistant_gate_fast 查看最终 prompt\\n"
                    "2. 直接基于真实源码文件做增量修改\\n"
                    "3. 避免采信模型虚构的方法名、字段名、路径名"
                )
"""

    text = replace_once(text, old_block, new_block, "chat() 门禁后返回逻辑")

    TARGET.write_text(text, encoding="utf-8")

    import py_compile
    py_compile.compile(str(TARGET), doraise=True)

    print("✅ patch 完成并通过语法检查")
    print("下一步运行：")
    print("python - <<'PY'")
    print("from core.aicore.aicore import get_aicore_instance")
    print("aicore = get_aicore_instance()")
    print("print(aicore.chat('现在三花聚顶的记忆层应该怎么接入 AICore？'))")
    print("PY")


if __name__ == "__main__":
    main()
