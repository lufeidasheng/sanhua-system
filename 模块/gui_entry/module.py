import logging

log = logging.getLogger(__name__)

def register_actions():
    """
    注册动作函数的地方
    """
    log.info(f"✨ [{__name__}] 默认入口被调用 (TODO: 实现业务逻辑)")

import logging
log = logging.getLogger(__name__)

def entry():
    log.info(f"✨ [{__name__}] 默认入口被调用 (TODO: 实现业务逻辑)")
