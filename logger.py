from pydantic import BaseModel
import logging
from collections import deque
from typing import Optional

class ExcludeDashboardAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Buang log akses HTTP dari uvicorn.access
        if record.name == "uvicorn.access":
            return False

        msg = record.getMessage()
        ignored_phrases = [
            "/api/logs/agent-events",
            "HTTP Request: ",
            "/v3/",
            '"GET ',
            '"POST ',
            '"PUT ',
            '"DELETE ',
            "response_closed.",
            "receive_response_body.",
            "receive_response_headers.",
            "send_request_body.",
            "send_request_headers.",
            "connect_tcp.",
            "close_socket.",
        ]
        if any(phrase in msg for phrase in ignored_phrases):
            return False

        return True

class DashboardLogHandler(logging.Handler):
    def __init__(self, max_entries=5000):
        super().__init__()
        self.records = deque(maxlen=max_entries)

    def emit(self, record):
        self.records.append({
            "timestamp": self.formatter.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage()
        })


dashboard_log_handler = DashboardLogHandler()
dashboard_log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
dashboard_log_handler.addFilter(ExcludeDashboardAccessFilter())
dashboard_log_handler.setLevel(logging.DEBUG)

# Set levels for noisy third-party loggers
for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    l = logging.getLogger(name)
    l.addHandler(dashboard_log_handler)
    l.setLevel(logging.WARNING)

# Root logger should stay at INFO to avoid library debug noise
root_logger = logging.getLogger("")
root_logger.addHandler(dashboard_log_handler)
root_logger.setLevel(logging.INFO)

# Specifically set mediamtx to DEBUG to see app-specific debug logs
logging.getLogger("mediamtx.client").setLevel(logging.DEBUG)

# Handler level should be DEBUG to capture everything
dashboard_log_handler.setLevel(logging.DEBUG)

agent_logger = logging.getLogger("mediamtx.agent")
agent_logger.setLevel(logging.INFO)
agent_logger.propagate = True

class AgentLogPayload(BaseModel):
    timestamp: Optional[str] = None
    level: Optional[str] = "INF"
    message: str
    source: Optional[str] = "mediamtx"
