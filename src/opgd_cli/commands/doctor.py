"""诊断命令：opgd doctor —— 服务连通性 / 登录态 / 额度自检。"""

from __future__ import annotations

from typing import Optional

import httpx
import typer
from rich.table import Table

from ..config import get_profile
from ..exceptions import AuthError, OPGDCLIError
from ..runtime import SERVER_OPTION, console, handle_errors, make_client


@handle_errors
def doctor(
    server: Optional[str] = SERVER_OPTION,
) -> None:
    """检查服务端连通性、登录状态与账号额度，用于快速定位环境问题。"""
    profile = get_profile(server)
    results: list[tuple[str, bool, str]] = []

    # 1. 配置
    results.append(("配置文件 ~/.opgd/config.toml", True, f"服务端 {profile.server}"))

    # 2. 服务健康
    try:
        with make_client(server) as client:
            health = client.health()
            payload = health.get("data") if isinstance(health.get("data"), dict) else health
            status = str(payload.get("status", ""))
            ok = status.lower() in ("ok", "healthy", "up", "")
            detail = f"{status} · {payload.get('service', '')} v{payload.get('version', '?')}"
            results.append(("服务健康检查 /health", ok, detail))

            # 3. 登录态
            if profile.access_token:
                try:
                    p = client.profile()
                    results.append(("登录状态", True, f"{p.get('username', '?')}（{p.get('role_label') or p.get('role', 'USER')}）"))
                    quota = p.get("remaining_quota")
                    if quota is not None:
                        results.append(("分析额度", int(quota) > 0, f"剩余 {quota} 次"))
                except AuthError:
                    results.append(("登录状态", False, "凭据已过期 → opgd auth login"))
            else:
                results.append(("登录状态", False, "未登录（正式通道不可用，trial 不受影响）"))
    except OPGDCLIError as exc:
        results.append(("服务健康检查 /health", False, exc.message))
    except httpx.HTTPError as exc:
        results.append(("服务健康检查 /health", False, f"网络异常：{exc}"))

    table = Table(title="[bold]opgd doctor 自检结果[/bold]", show_header=True, header_style="bold")
    table.add_column("检查项")
    table.add_column("状态", justify="center")
    table.add_column("详情", overflow="fold")
    for name, ok, detail in results:
        mark = "[green]✔[/green]" if ok else "[red]✗[/red]"
        table.add_row(name, mark, detail)
    console.print(table)

    failed = [r for r in results if not r[1]]
    if failed:
        console.print(f"\n[yellow]{len(failed)} 项未通过；按详情提示处理即可。[/yellow]")
        raise typer.Exit(code=1)
    console.print("\n[green]全部通过，环境正常。[/green]")
