"""任务轮询：带指数退避与 Rich 进度展示。"""

from __future__ import annotations

import signal
import time
from typing import Callable, Dict, List, Optional

from rich.console import Console

from .exceptions import OPGDCLIError, TaskFailedError

TERMINAL_OK = {"SUCCESS"}
TERMINAL_BAD = {"FAILED", "CANCELLED"}
ALL_TERMINAL = TERMINAL_OK | TERMINAL_BAD

# 状态中文标签
STATUS_LABELS = {
    "PENDING": "排队中",
    "PROCESSING": "计算中",
    "SUCCESS": "完成",
    "FAILED": "失败",
    "CANCEL_REQUESTED": "取消中",
    "CANCELLED": "已取消",
}


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


class TaskInterrupted(OPGDCLIError):
    """等待过程中用户 Ctrl+C。"""

    exit_code = 130

    def __init__(self, task_id: str):
        super().__init__(f"等待已中断；任务 {task_id} 仍在服务端运行，可用 opgd status {task_id} 查看进度")
        self.task_id = task_id


def wait_for_task(
    client,
    task_id: str,
    *,
    console: Console,
    poll_interval: float = 2.0,
    max_interval: float = 15.0,
    timeout: Optional[float] = 1800.0,
    on_tick: Optional[Callable[[Dict], None]] = None,
) -> Dict:
    """轮询直到任务终态，返回最终任务 JSON。

    - 指数退避：2s → 15s 封顶
    - timeout 为 None 表示无限等待
    - Ctrl+C 抛 TaskInterrupted（任务仍在服务端跑，不丢）
    """
    started = time.monotonic()
    interval = poll_interval
    spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    tick = 0

    def _handle_sigint(signum, frame):  # noqa: ANN001
        raise TaskInterrupted(task_id)

    prev_handler = None
    try:
        try:
            prev_handler = signal.signal(signal.SIGINT, _handle_sigint)
        except ValueError:  # 非主线程
            prev_handler = None

        while True:
            task = client.get_task(task_id)
            status = task.get("status", "")
            if on_tick:
                on_tick(task)
            if status in ALL_TERMINAL:
                if status in TERMINAL_BAD:
                    raise TaskFailedError(task_id, status, task.get("error") or "")
                return task
            if timeout is not None and time.monotonic() - started > timeout:
                raise OPGDCLIError(f"等待超时（{timeout:.0f}s）；任务 {task_id} 仍在服务端运行，可稍后 opgd status {task_id}")

            elapsed = int(time.monotonic() - started)
            spinner = spinner_chars[tick % len(spinner_chars)]
            console.print(
                f"\r[cyan]{spinner}[/cyan] 任务 {task_id[:12]}… [{status_label(status)}] "
                f"已等待 {elapsed}s（Ctrl+C 中断等待，任务不终止）",
                end="",
            )
            time.sleep(interval)
            tick += 1
            interval = min(max_interval, interval * 1.5)
            console.print("\r\x1b[2K", end="")
    finally:
        if prev_handler is not None:
            try:
                signal.signal(signal.SIGINT, prev_handler)
            except ValueError:
                pass
        console.print("\r\x1b[2K", end="")


def summarize_steps(client, task_id: str, console: Console) -> List[str]:
    """輸出等待期间的关键信息（预留扩展）。"""
    return []
