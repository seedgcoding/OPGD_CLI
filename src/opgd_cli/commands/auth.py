"""认证命令：login / logout / whoami。"""

from __future__ import annotations

from typing import Optional

import typer
from rich.panel import Panel

from ..config import clear_auth, get_profile, prompt_credentials, save_auth
from ..exceptions import AuthError
from ..runtime import JSON_OPTION, SERVER_OPTION, console, handle_errors, make_client, print_json

app = typer.Typer(help="账号登录与凭据管理", no_args_is_help=True)


@app.command()
@handle_errors
def login(
    server: Optional[str] = SERVER_OPTION,
    username: Optional[str] = typer.Option(None, "--username", "-u", help="账号（省略则交互输入）"),
    password_stdin: bool = typer.Option(False, "--password-stdin", help="从标准输入读取密码（适合脚本/CI）"),
    otp_code: Optional[str] = typer.Option(None, "--otp", help="两步验证码（账号启用 2FA 时提供）"),
) -> None:
    """登录 OPGD 平台并把 token 保存到本地。"""
    if password_stdin:
        import sys

        if not username:
            console.print("[red]--password-stdin 需要配合 --username 使用[/red]")
            raise typer.Exit(code=1)
        password = sys.stdin.readline().rstrip("\r\n")
        if not password:
            raise typer.Exit(code=1)
    elif not username:
        username, password = prompt_credentials()
    else:
        import getpass

        password = getpass.getpass("密码: ")
    if not password_stdin and not otp_code:
        # 服务端简化登录：账号密码正确即发 token；--otp 预留给未来 2FA 强化
        otp_code = None

    with make_client(server) as client:
        token = client.login(username, password)
        access_token = token.get("access_token")
        if not access_token:
            console.print("[red]登录响应中没有 access_token[/red]")
            raise typer.Exit(code=1)
        token_type = token.get("token_type", "bearer")
        # 保存凭据（用实际请求的 server 地址）
        actual_server = client.server
        save_auth(actual_server, access_token, token_type, username)
        # 顺手拉用户信息展示
        try:
            me = client.me()
            display = me.get("username") or me.get("email") or username
            quota = me.get("remaining_quota")
            extra = f"  剩余额度：{quota}" if quota is not None else ""
        except Exception:
            display = username
            extra = ""
        console.print(
            Panel(
                f"[green]✔ 登录成功[/green]  欢迎你，[bold]{display}[/bold]{extra}\n"
                f"[dim]凭据已保存到 ~/.opgd/config.toml（服务端：{actual_server}）[/dim]",
                border_style="green",
                expand=False,
            )
        )


@app.command()
@handle_errors
def logout(
    server: Optional[str] = SERVER_OPTION,
) -> None:
    """清除本地保存的登录凭据。"""
    removed = clear_auth(server)
    if removed:
        console.print("[green]✔ 已清除本地凭据[/green]")
    else:
        console.print("[yellow]该服务端本来就没有保存凭据[/yellow]")


@app.command("whoami")
@handle_errors
def whoami(
    server: Optional[str] = SERVER_OPTION,
    as_json: bool = JSON_OPTION,
) -> None:
    """查看当前登录账号与剩余额度。"""
    profile = get_profile(server)
    if not profile.access_token:
        console.print("[yellow]未登录[/yellow]（执行 opgd login 登录，或使用免登录的 opgd trial）")
        console.print(f"[dim]当前服务端：{profile.server}[/dim]")
        raise typer.Exit(code=0)
    try:
        with make_client(server) as client:
            try:
                info = client.profile()
            except Exception:
                info = client.me()
    except AuthError:
        console.print("[yellow]登录凭据已过期，请重新执行 opgd login[/yellow]")
        raise typer.Exit(code=3)
    if as_json:
        print_json(info)
        return
    display = info.get("username") or info.get("email") or "?"
    quota = info.get("remaining_quota", info.get("ai_tokens"))
    consumed = info.get("consumed_count")
    lines = [f"[bold]{display}[/bold]"]
    if info.get("role_label") or info.get("role"):
        lines.append(f"角色：{info.get('role_label') or info.get('role')}")
    if quota is not None:
        text = f"剩余分析次数：{quota}"
        if consumed is not None:
            text += f"（已用 {consumed}）"
        lines.append(text)
    if info.get("account_status_label"):
        lines.append(f"账号状态：{info['account_status_label']}")
    if info.get("created_at"):
        lines.append(f"[dim]注册于 {str(info['created_at'])[:19].replace('T', ' ')}[/dim]")
    console.print(Panel("\n".join(lines), title=f"{profile.server}", border_style="cyan", expand=False))
