# tools/test_decision_chain.py
from pprint import pprint
from core.aicore.aicore import get_aicore_instance

aicore = get_aicore_instance()

text = """
1. 先调用 sysmon.status 查看系统状态
2. 再调用 ai.ask 分析当前错误原因
3. 如需修改配置，先人工确认
"""

result = aicore.process_suggestion_chain(
    suggestion_text=text,
    user_query="帮我分析系统状态",
    dry_run=True,
)

pprint(result)
