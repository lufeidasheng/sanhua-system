import logging
import logging.handlers
import os
import json
import threading
import sys
from typing import Any, Dict, Optional

# ===== 国际化支持（自动加载 i18n/zh_CN.json，可切换，默认找不到不报错） =====
def load_i18n_map(lang="zh_CN"):
    i18n_dir = os.path.join(os.path.dirname(__file__), "i18n")
    i18n_file = os.path.join(i18n_dir, f"{lang}.json")
    if os.path.exists(i18n_file):
        try:
            with open(i18n_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

_I18N_LANG = os.getenv("I18N_LANG", "zh_CN")
_I18N_MAP = load_i18n_map(_I18N_LANG)

def set_i18n_lang(lang: str = "zh_CN"):
    global _I18N_LANG, _I18N_MAP
    _I18N_LANG = lang
    _I18N_MAP = load_i18n_map(lang)

# ========== 日志主类 ==========
class TraceLogger:
    _configured_loggers: Dict[str, "TraceLogger"] = {}

    def __new__(cls, name: str = "三花聚顶") -> "TraceLogger":
        if name not in cls._configured_loggers:
            instance = super().__new__(cls)
            instance._init_logger(name)
            cls._configured_loggers[name] = instance
        return cls._configured_loggers[name]

    def _init_logger(self, name: str) -> None:
        self.logger = logging.getLogger(name)
        if self.logger.handlers:
            return  # 已初始化过则跳过

        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        use_json = os.getenv("LOG_JSON", "false").lower() == "true"
        max_bytes = int(os.getenv("LOG_MAX_BYTES", "10485760"))
        backup_count = int(os.getenv("LOG_BACKUP_COUNT", "5"))

        log_dir = os.path.expanduser(os.getenv("LOG_DIR", "~/聚核助手2.0/logs"))
        os.makedirs(log_dir, exist_ok=True)
        default_log_file = os.path.join(log_dir, f"{name}.log")
        log_file = os.getenv("LOG_FILE", default_log_file)
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        self.logger.setLevel(getattr(logging, log_level, logging.INFO))

        formatter = JsonFormatter() if use_json else logging.Formatter(
            '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        if os.getenv("CONSOLE_LOG", "true").lower() == "true":
            console_handler = logging.StreamHandler()
            console_handler.setLevel(getattr(logging, log_level, logging.INFO))
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

        file_handler = logging.handlers.RotatingFileHandler(
            filename=log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(getattr(logging, log_level, logging.INFO))
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

        logging.captureWarnings(True)

    # ===== i18n 替换 =====
    def _i18n_format(self, msg: str, extra: Optional[Dict[str, Any]]) -> str:
        tpl = _I18N_MAP.get(msg, msg)
        try:
            return tpl.format(**(extra or {}))
        except Exception:
            return tpl

    # ===== 统一API =====
    def debug(self, msg: str, extra: Optional[Dict[str, Any]] = None, exc_info: Optional[bool] = None) -> None:
        self._log(logging.DEBUG, msg, extra, exc_info)

    def info(self, msg: str, extra: Optional[Dict[str, Any]] = None, exc_info: Optional[bool] = None) -> None:
        self._log(logging.INFO, msg, extra, exc_info)

    def warning(self, msg: str, extra: Optional[Dict[str, Any]] = None, exc_info: Optional[bool] = None) -> None:
        self._log(logging.WARNING, msg, extra, exc_info)

    def error(self, msg: str, extra: Optional[Dict[str, Any]] = None, exc_info: Optional[bool] = None) -> None:
        self._log(logging.ERROR, msg, extra, exc_info)

    def critical(self, msg: str, extra: Optional[Dict[str, Any]] = None, exc_info: Optional[bool] = None) -> None:
        self._log(logging.CRITICAL, msg, extra, exc_info)

    def _log(
        self,
        level: int,
        msg: str,
        extra: Optional[Dict[str, Any]] = None,
        exc_info: Optional[bool] = None
    ) -> None:
        if extra is None:
            extra = {}
        msg_fmt = self._i18n_format(msg, extra)
        filtered_extra = {k: v for k, v in extra.items()
                          if k not in ("process", "thread", "threadName", "processName")}
        exc_info_val = sys.exc_info() if exc_info is True else exc_info
        self.logger.log(level, msg_fmt, extra=filtered_extra, exc_info=exc_info_val)

# ========== JSON日志格式化 ==========
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "pid": getattr(record, "process", None),
            "thread": getattr(record, "threadName", None)
        }
        standard_attrs = {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
            "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "created", "msecs", "relativeCreated", "thread", "threadName",
            "processName", "process", "message", "asctime"
        }
        for key, value in record.__dict__.items():
            if key not in standard_attrs:
                log_record[key] = value
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record, ensure_ascii=False)

# ========== 工厂 ==========
def get_logger(name="三花聚顶") -> TraceLogger:
    return TraceLogger(name)

def configure_logging(
    level: str = "INFO",
    log_dir: str = None,
    json_format: bool = False,
    i18n_lang: str = "zh_CN"
):
    set_i18n_lang(i18n_lang)
    # 可扩展全局logdir/json等
