"""JSON logs: one JSON object per line, with the request id while a request runs."""

import logging
import sys
from typing import TextIO

import structlog

# Fields added to every log line, ours and those of libraries such as uvicorn.
_COMMON_STEPS = [
    structlog.contextvars.merge_contextvars,  # request_id, set by the request id middleware
    structlog.stdlib.add_logger_name,
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
]


def json_handler(stream: TextIO | None = None) -> logging.Handler:
    """A standard logging handler that writes every record as one JSON line."""
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=_COMMON_STEPS,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
        )
    )
    return handler


def configure_logging(level: str) -> None:
    structlog.configure(
        processors=[*_COMMON_STEPS, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
    )
    root = logging.getLogger()
    root.handlers = [json_handler()]
    root.setLevel(level.upper())
    # Uvicorn prints plain-text lines; send them through our JSON handler instead,
    # and turn off its access line, which would repeat our "request" line.
    logging.getLogger("uvicorn").handlers = []
    logging.getLogger("uvicorn").propagate = True
    logging.getLogger("uvicorn.access").disabled = True
