from .gui_memory_bridge import (
    append_action,
    append_chat,
    build_prompt,
    collect_context,
    display_is_polluted,
    execute,
    extract_text,
    install_memory_pipeline,
    sanitize_reply_for_writeback,
    try_local_memory_answer,
)
from .chat_orchestrator import GUIChatOrchestrator
from .alias_bootstrap import bootstrap_aliases, count_dispatcher_aliases
