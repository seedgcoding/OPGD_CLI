"""OPGD CLI 应用入口。

opgd = OPGD 地理探测器平台命令行客户端
"""

from __future__ import annotations

import typer

from . import __version__
from .commands import analyze, auth, report, trial, upload
from .commands.doctor import doctor as _doctor

app = typer.Typer(
    name="opgd",
    help=(
        "[bold]OPGD[/bold] —— OPGD 地理探测器平台命令行客户端\n\n"
        "免登录试用：[bold]opgd trial data.csv -y GDP -x X1 X2[/bold]\n"
        "正式通道（完整报告/导出）：[bold]opgd login[/bold] 后 [bold]opgd analyze ...[/bold]\n\n"
        "[dim]退出码：0 成功 · 2 服务端/网络错误 · 3 登录过期 · 4 额度不足 · "
        "5 限流(稍后重试) · 6 任务失败 · 7 未登录 · 130 用户中断[/dim]"
    ),
    no_args_is_help=True,
    add_completion=True,
    rich_markup_mode="rich",
)

app.add_typer(auth.app, name="auth", help="登录 / 登出 / 账号信息")
app.add_typer(upload.app, name="", help="上传数据文件")
app.add_typer(trial.app, name="", help="免登录试用通道")
app.add_typer(analyze.app, name="", help="正式通道分析与任务管理")
app.add_typer(report.app, name="", help="报告查看与导出")
app.command(name="doctor", help="环境自检（连通性/登录态/额度）")(_doctor)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"opgd-cli {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True, help="显示版本号"
    ),
) -> None:
    """OPGD 地理探测器平台命令行客户端。"""


def main() -> None:
    """console_scripts 入口：opgd = opgd_cli.app:main"""
    app()


# 兼容 python -m opgd_cli
if __name__ == "__main__":  # pragma: no cover
    main()
