# package exports kept minimal and lazy to avoid circular imports

__all__ = ["SanHuaTongYu", "get_action_dispatcher"]


def __getattr__(name):
    if name == "SanHuaTongYu":
        from .master import SanHuaTongYu as _SanHuaTongYu
        globals()["SanHuaTongYu"] = _SanHuaTongYu
        return _SanHuaTongYu
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_action_dispatcher():
    from .action_dispatcher import ACTION_MANAGER
    return ACTION_MANAGER
