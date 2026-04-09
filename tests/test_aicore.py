from core.aicore.aicore import AICore

def test_aicore_basic_chat():
    ai = AICore()
    response = ai.chat("你好")
    assert isinstance(response, str)
    assert len(response.strip()) > 0
