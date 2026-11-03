"""应用日志配置。

LOG_LEVEL 控制等级，LOG_FORMAT=json 时每行输出一条 JSON 日志。
"""
import logging
import os
import json


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    raw_format = os.getenv(
        "LOG_FORMAT",
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    log_format = (
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
        if raw_format.strip().lower() == "json"
        else raw_format
    )

    logging.basicConfig(
        level=level,
        format=log_format,
        force=True,
    )
    if raw_format.strip().lower() == "json":
        for handler in logging.getLogger().handlers:
            handler.setFormatter(JsonFormatter())
