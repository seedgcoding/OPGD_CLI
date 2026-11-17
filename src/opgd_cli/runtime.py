"""命令运行时辅助：客户端构造与统一错误处理。"""

from __future__ import annotations

import functools
import os
import sys
from typing import Callable, Optional

import httpx
import typer
from rich.console import Console

from .client import OPGDClient
from .config import get_profile
from .exceptions import (
    APIError,
    AuthError,
    OPGDCLIError,
    QuotaError,
    RateLimitError,
    TaskFailedError,
)

console = Console()
err_console = Console(stderr=True, style="red")


def print_json(data) -> None:
    """--json 输出：必须绕过 Rich（软换行会破坏 JSON），直接写 stdout。"""
    from .client import dump_json

    sys.stdout.write(dump_json(data) + "\n")


def make_client(server: Optional[str] = None) -> OPGDClient:
    """依据 --server/环境变量/配置文件构造客户端。

    代理优先级：OPGD_NO_PROXY 环境变量 > 配置文件记忆（no_proxy=true）> 默认走系统代理（失败自动直连）。
    """
    profile = get_profile(server)
    env_value = os.environ.get("OPGD_NO_PROXY", "").strip().lower()
    if env_value in ("1", "true", "yes"):
        no_proxy = True
    elif env_value in ("0", "false", "no"):
        no_proxy = False
    else:
        no_proxy = bool(getattr(profile, "no_proxy", False))
    return OPGDClient(profile, use_proxy=not no_proxy)


def handle_errors(func: Callable) -> Callable:
    """把 CLI 异常翻译成友好的终端输出 + 语义化退出码。"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except typer.Exit:
            raise
        except AuthError as exc:
            err_console.print(f"认证失败：{exc.message}")
            err_console.print("[dim]提示：token 可能已过期，请重新执行 opgd login[/dim]")
            raise typer.Exit(code=exc.exit_code)
        except QuotaError as exc:
            err_console.print(f"额度不足：{exc.message}")
            err_console.print("[dim]提示：免费试用通道有次数限制，登录正式账号可获得更多额度[/dim]")
            raise typer.Exit(code=exc.exit_code)
        except RateLimitError as exc:
            wait = f"，请 {exc.retry_after} 秒后重试" if exc.retry_after else "，请稍后重试"
            err_console.print(f"触发服务端限流{wait}")
            raise typer.Exit(code=exc.exit_code)
        except TaskFailedError as exc:
            err_console.print(str(exc))
            raise typer.Exit(code=exc.exit_code)
        except APIError as exc:
            err_console.print(f"服务端错误：{exc.message}")
            raise typer.Exit(code=exc.exit_code)
        except OPGDCLIError as exc:
            err_console.print(str(exc.message))
            raise typer.Exit(code=exc.exit_code)
        except httpx.ConnectError as exc:
            err_console.print(f"无法连接服务端：{exc}")
            err_console.print("[dim]提示：可用 --server 指定其他服务地址[/dim]")
            raise typer.Exit(code=2)
        except httpx.TimeoutException as exc:
            err_console.print(f"请求超时：{exc}")
            raise typer.Exit(code=2)

    return wrapper


SERVER_OPTION = typer.Option(None, "--server", "-s", help="服务端地址（默认读 ~/.opgd/config.toml 或 OPGD_SERVER 环境变量）")
JSON_OPTION = typer.Option(False, "--json", help="以原始 JSON 输出（适合脚本/管道）")
