"""OPGD CLI 异常体系。

所有 API 错误统一由 :class:`APIError` 及其子类表达，命令层据此给出友好提示。
"""

from __future__ import annotations

from typing import Any, Optional


class OPGDCLIError(Exception):
    """CLI 基础异常，所有可预期错误都继承自它。"""

    #: 退出码，Typer/argparse 风格
    exit_code: int = 1

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class APIError(OPGDCLIError):
    """服务端返回了非 2xx 响应。"""

    exit_code = 2

    def __init__(self, status_code: int, detail: Any, *, server: str = ""):
        self.status_code = status_code
        self.detail = detail
        self.server = server
        super().__init__(self._format())

    def _format(self) -> str:
        detail = self.detail
        if isinstance(detail, dict):
            # FastAPI 校验错误形如 {"detail": [...]}，取每条 msg 拼接
            msgs = detail.get("detail")
            if isinstance(msgs, list):
                detail = "; ".join(
                    m.get("msg", str(m)) if isinstance(m, dict) else str(m) for m in msgs
                )
            else:
                detail = msgs or detail
        return f"[{self.status_code}] {detail or '服务端错误'}"


class AuthError(APIError):
    """401/403：未登录或凭据失效。"""

    exit_code = 3


class QuotaError(APIError):
    """额度不足或免费通道次数用尽。"""

    exit_code = 4


class RateLimitError(APIError):
    """429：触发服务端限流。"""

    exit_code = 5

    def __init__(self, status_code: int, detail: Any, *, retry_after: Optional[int] = None, server: str = ""):
        super().__init__(status_code, detail, server=server)
        self.retry_after = retry_after


class TaskFailedError(OPGDCLIError):
    """分析任务以 FAILED/CANCELLED 终止。"""

    exit_code = 6

    def __init__(self, task_id: str, status: str, error_message: str = ""):
        self.task_id = task_id
        self.status = status
        super().__init__(f"任务 {task_id} 状态为 {status}" + (f"：{error_message}" if error_message else ""))


class NotLoggedInError(OPGDCLIError):
    """正式通道命令在未登录时调用。"""

    exit_code = 7

    def __init__(self):
        super().__init__("尚未登录，请先执行 opgd login（或使用免登录的 opgd trial 命令）")
