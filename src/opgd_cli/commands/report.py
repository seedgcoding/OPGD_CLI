"""报告命令：report 终端渲染 / export 下载。"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Optional

import typer
from rich.panel import Panel

from ..runtime import print_json
from ..exceptions import OPGDCLIError
from ..runtime import SERVER_OPTION, console, handle_errors, make_client
from ..render import render_full_report

app = typer.Typer(help="查看与导出分析报告", no_args_is_help=True)


@app.command()
@handle_errors
def report(
    task_id: str = typer.Argument(..., help="任务 ID"),
    server: Optional[str] = SERVER_OPTION,
    as_json: bool = typer.Option(False, "--json", help="以原始 JSON 输出"),
) -> None:
    """在终端渲染任务的完整报告（四探测器）。"""
    with make_client(server) as client:
        report_data = client.get_report(task_id)
    if as_json:
        print_json(report_data)
    else:
        render_full_report(report_data, console)


@app.command("export")
@handle_errors
def export(
    task_id: str = typer.Argument(..., help="任务 ID"),
    output: Path = typer.Option(Path("."), "--output", "-o", help="输出目录（默认当前目录）"),
    unzip: bool = typer.Option(False, "--unzip", help="下载后解压到同名目录"),
    png: bool = typer.Option(False, "--png", help="额外下载因子/交互探测器图表 PNG"),
    server: Optional[str] = SERVER_OPTION,
) -> None:
    """下载报告 ZIP（可选解压与图表 PNG）。"""
    output.mkdir(parents=True, exist_ok=True)
    with make_client(server) as client:
        with console.status("[cyan]下载报告中…"):
            content, filename = client.export_report(task_id)
        zip_path = output / filename
        zip_path.write_bytes(content)
        console.print(f"[green]✔[/green] 报告已保存：{zip_path}（{len(content) / 1024:.1f} KB）")

        if "data-only" in filename:
            console.print("[yellow]注意：当前账号为数据导出模式（data-only），报告不含图表[/yellow]")

        if unzip:
            extract_dir = output / zip_path.stem
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(extract_dir)
            console.print(f"[green]✔[/green] 已解压到：{extract_dir}")

        if png:
            charts = {"factor": output / f"factor_detector_{task_id[:8]}.png",
                      "interaction": output / f"interaction_detector_{task_id[:8]}.png"}
            for name, dest in charts.items():
                try:
                    data = client.export_chart(task_id, name)
                    dest.write_bytes(data)
                    console.print(f"[green]✔[/green] {name} 图表：{dest}")
                except OPGDCLIError as exc:
                    console.print(f"[yellow]✗ {name} 图表下载失败：{exc.message}[/yellow]")
    console.print(
        Panel(f"[dim]提示：报告内含 HTML 交互图表，解压后用浏览器打开即可查看[/dim]", border_style="dim", expand=False)
    )
