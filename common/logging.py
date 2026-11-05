"""Structured (JSON-lines) logging for production log aggregation."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

# Attributes every LogRecord has. Anything else was passed via ``extra=``.
_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with ``extra=`` fields merged in.

    ``logger.info("order_created", extra={"order_id": 7})`` produces::

        {"timestamp": "...", "level": "INFO", "logger": "packwise.orders",
         "message": "order_created", "order_id": 7}
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)
