"""正式通道分析命令：analyze / status / wait / tasks / cancel。"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer
from rich.panel import Panel

from ..config import get_profile
from ..exceptions import NotLoggedInError, TaskFailedError
from ..polling import wait_for_task
from ..runtime import JSON_OPTION, SERVER_OPTION, console, handle_errors, make_client, print_json
from ..render import (
    render_full_report,
    render_task_list,
    render_task_status,
    render_upload_meta,
    warn_unspecified_categorical,
)
from ..utils import parse_bins, parse_floats, parse_methods, validate_upload_file

app = typer.Typer(help="提交分析任务与管理任务", no_args_is_help=True)


def _require_login(server: Optional[str]) -> None:
    profile = get_profile(server)
    if not profile.access_token:
        raise NotLoggedInError()


def _submit_and_maybe_wait(
    client,
    upload_result: Optional[dict],
    upload_id: Optional[int],
    y_col: str,
    x_cols: List[str],
    cat_cols: List[str],
    methods: List[str],
    min_bins: int,
    max_bins: int,
    model: str,
    fuzziness_mode: str,
    fz_values: Optional[List[float]],
    perm: int,
    title: Optional[str],
    wait: bool,
    as_json: bool,
    reused_upload_id: bool = False,
) -> None:
    if upload_result is not None:
        render_upload_meta(upload_result, console)
        if not as_json:
            warn_unspecified_categorical(upload_result, x_cols, cat_cols, console)
        upload_id = upload_result.get("id")
        if upload_id is None:
            console.print("[red]上传响应缺少 id，无法提交分析[/red]")
            raise typer.Exit(code=2)
    if not wait:
        result = client.analyze(
            upload_id, y_col, x_cols,
            title=title, analysis_model=model, categorical_cols=cat_cols,
            methods=methods, min_bins=min_bins, max_bins=max_bins,
            fuzziness_mode=fuzziness_mode, fuzziness_values=fz_values,
            num_permutations=perm,
        )
        console.print(Panel(
            f"任务已提交：[bold cyan]{result.get('task_id')}[/bold cyan]\n"
            f"状态：{result.get('status', '-')}  剩余额度：{result.get('remaining_quota', '-')}\n"
            f"[dim]查看进度：opgd status {result.get('task_id')}[/dim]",
            title="已受理", border_style="green", expand=False,
        ))
        return

    # 先提交，再轮询
    result = client.analyze(
        upload_id, y_col, x_cols,
        title=title, analysis_model=model, categorical_cols=cat_cols,
        methods=methods, min_bins=min_bins, max_bins=max_bins,
        fuzziness_mode=fuzziness_mode, fuzziness_values=fz_values,
        num_permutations=perm,
    )
    task_id = result.get("task_id")
    quota = result.get("remaining_quota")
    console.print(f"[dim]任务已受理：{task_id}" + (f"（剩余额度 {quota}）" if quota is not None else "") + "[/dim]")
    try:
        wait_for_task(client, task_id, console=console)
    except TaskFailedError as exc:
        if reused_upload_id and "No such file" in (exc.args[0] if exc.args else ""):
            console.print(
                "[yellow]提示：--upload-id 对应的文件已被上一次分析消费。"
                "平台在任务结束后会删除上传文件，每次上传只能分析一次；"
                "请改用文件路径模式重新上传：opgd analyze <file> -y ... -x ...[/yellow]"
            )
        raise
    report = client.get_report(task_id)
    if as_json:
        print_json(report)
    else:
        render_full_report(report, console)


@app.command()
@handle_errors
def analyze(
    file: Optional[Path] = typer.Argument(None, help="数据文件（与 --upload-id 二选一）"),
    y: str = typer.Option(..., "--y", "-y", help="因变量列名"),
    x: List[str] = typer.Option(..., "--x", "-x", help="自变量列名：重复 -x 或逗号分隔，如 -x X1 -x X2 / -x X1,X2,X3"),
    cat: List[str] = typer.Option([], "--cat", "-c", help="类型（分类）变量：重复 -c 或逗号分隔，必须来自 -x 列表"),
    methods: Optional[str] = typer.Option(None, "--methods", "-m", help="离散化方法，逗号分隔（默认 4 种常用方法）"),
    bins: Optional[str] = typer.Option(None, "--bins", "-b", help="分级数范围，如 3:8（默认 3:8）"),
    model: str = typer.Option("opgd", "--model", help="分析模型：opgd / fuzzygd"),
    fuzziness: str = typer.Option("quick", "--fuzziness", help="模糊系数模式（仅 fuzzygd）：quick / fine / custom"),
    fz_values: Optional[str] = typer.Option(None, "--fz-values", help="自定义模糊系数，逗号分隔（配合 --fuzziness custom）"),
    perm: int = typer.Option(99, "--perm", help="置换检验次数（0~5000，仅 fuzzygd）"),
    upload_id: Optional[int] = typer.Option(None, "--upload-id", help="复用已上传文件（一次性：任务结束后平台会删除文件）"),
    title: Optional[str] = typer.Option(None, "--title", help="任务标题"),
    no_wait: bool = typer.Option(False, "--no-wait", help="只提交任务不等待，打印 task_id 后退出"),
    server: Optional[str] = SERVER_OPTION,
    as_json: bool = JSON_OPTION,
) -> None:
    """提交正式通道分析（需先 opgd login）：上传 → 提交 → 轮询 → 渲染报告。"""
    _require_login(server)
    if file is None and upload_id is None:
        console.print("[red]必须提供数据文件或 --upload-id[/red]")
        raise typer.Exit(code=1)
    if file is not None and upload_id is not None:
        console.print("[red]file 与 --upload-id 只能二选一[/red]")
        raise typer.Exit(code=1)

    # -x 支持 "X1,X2" 与多次 -x 混用
    x_cols: List[str] = []
    for item in x:
        x_cols.extend(part.strip() for part in item.replace("，", ",").split(",") if part.strip())
    cat_cols: List[str] = []
    for item in cat:
        cat_cols.extend(part.strip() for part in item.replace("，", ",").split(",") if part.strip())
    if y in x_cols:
        console.print("[red]因变量 Y 不能同时作为自变量 X[/red]")
        raise typer.Exit(code=1)
    invalid_cat = [c for c in cat_cols if c not in x_cols]
    if invalid_cat:
        console.print(f"[red]类型变量必须来自自变量列表：{', '.join(invalid_cat)}[/red]")
        raise typer.Exit(code=1)
    if model not in ("opgd", "fuzzygd"):
        console.print("[red]--model 仅支持 opgd / fuzzygd[/red]")
        raise typer.Exit(code=1)
    if not (0 <= perm <= 5000):
        console.print("[red]置换检验次数需在 0~5000 之间[/red]")
        raise typer.Exit(code=1)

    min_bins, max_bins = parse_bins(bins)
    method_list = parse_methods(methods, model)
    fz_list = parse_floats(fz_values) if fz_values else None
    if model == "fuzzygd" and fuzziness == "custom" and not fz_list:
        console.print("[red]--fuzziness custom 需要 --fz-values[/red]")
        raise typer.Exit(code=1)

    with make_client(server) as client:
        upload_result = None
        if file is not None:
            path = validate_upload_file(file)
            upload_result = client.upload(path)
        _submit_and_maybe_wait(
            client, upload_result, upload_id, y, x_cols, cat_cols, method_list,
            min_bins, max_bins, model, fuzziness, fz_list, perm, title,
            wait=not no_wait, as_json=as_json,
            reused_upload_id=(file is None and upload_id is not None),
        )


@app.command("status")
@handle_errors
def status(
    task_id: str = typer.Argument(..., help="任务 ID"),
    server: Optional[str] = SERVER_OPTION,
    as_json: bool = JSON_OPTION,
) -> None:
    """查询任务状态。"""
    _require_login(server)
    with make_client(server) as client:
        task = client.get_task(task_id)
    if as_json:
        print_json(task)
    else:
        render_task_status(task, console)


@app.command("wait")
@handle_errors
def wait(
    task_id: str = typer.Argument(..., help="任务 ID"),
    timeout: Optional[int] = typer.Option(None, "--timeout", help="最长等待秒数（默认 1800）"),
    server: Optional[str] = SERVER_OPTION,
    as_json: bool = JSON_OPTION,
) -> None:
    """等待任务完成并渲染报告。"""
    _require_login(server)
    with make_client(server) as client:
        task = wait_for_task(client, task_id, console=console, timeout=float(timeout) if timeout else 1800.0)
        if task.get("status") == "SUCCESS":
            report = client.get_report(task_id)
            if as_json:
                print_json(report)
            else:
                render_full_report(report, console)
        else:
            render_task_status(task, console)


@app.command("tasks")
@handle_errors
def tasks(
    limit: int = typer.Option(10, "--limit", "-n", min=1, max=50, help="列出条数"),
    task_type: Optional[str] = typer.Option(None, "--type", help="按任务类型过滤（如 opgd_analysis）"),
    server: Optional[str] = SERVER_OPTION,
    as_json: bool = JSON_OPTION,
) -> None:
    """列出我的历史任务。"""
    _require_login(server)
    with make_client(server) as client:
        items = client.list_tasks(task_type=task_type, limit=limit)
    if as_json:
        print_json(items)
    else:
        render_task_list(items, console)


@app.command("cancel")
@handle_errors
def cancel(
    task_id: str = typer.Argument(..., help="任务 ID"),
    server: Optional[str] = SERVER_OPTION,
) -> None:
    """取消一个排队中/计算中的任务。"""
    _require_login(server)
    with make_client(server) as client:
        client.cancel_task(task_id)
    console.print(f"[green]✔ 已请求取消任务 {task_id}[/green]")
