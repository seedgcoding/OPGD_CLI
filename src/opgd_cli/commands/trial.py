"""免费试用通道：trial 命令（免登录，同步返回）。"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer
from rich.panel import Panel

from ..runtime import SERVER_OPTION, console, handle_errors, make_client, print_json
from ..render import render_trial_report, render_upload_meta, warn_unspecified_categorical
from ..utils import validate_upload_file

app = typer.Typer(help="免登录试用通道", no_args_is_help=True)


@app.command()
@handle_errors
def trial(
    file: Path = typer.Argument(..., help="CSV/Excel 数据文件（≤50MB）"),
    y: str = typer.Option(..., "--y", "-y", help="因变量列名"),
    x: List[str] = typer.Option(..., "--x", "-x", help="自变量列名：重复 -x 或逗号分隔，如 -x X1 -x X2 / -x X1,X2,X3"),
    cat: List[str] = typer.Option([], "--cat", "-c", help="类型（分类）变量：重复 -c 或逗号分隔，必须来自 -x 列表"),
    server: Optional[str] = SERVER_OPTION,
    as_json: bool = typer.Option(False, "--json", help="以原始 JSON 输出"),
) -> None:
    """免登录快速分析：上传 → 同步分析 → 终端渲染因子探测结果。

    免费试用通道无需账号，但有次数/规模限制（离散化方法与分级数由服务端自动寻优），
    且仅展示因子探测器；完整报告请 opgd login 后使用 opgd analyze。
    """
    path = validate_upload_file(file)

    x_cols: List[str] = []
    for item in x:
        x_cols.extend(part.strip() for part in item.replace("，", ",").split(",") if part.strip())
    cat_cols: List[str] = []
    for item in cat:
        cat_cols.extend(part.strip() for part in item.replace("，", ",").split(",") if part.strip())
    if y in x_cols:
        console.print("[red]因变量 Y 不能同时作为自变量 X[/red]")
        raise typer.Exit(code=1)
    if not x_cols:
        console.print("[red]至少需要一个自变量 -x[/red]")
        raise typer.Exit(code=1)
    invalid_cat = [c for c in cat_cols if c not in x_cols]
    if invalid_cat:
        console.print(f"[red]类型变量必须来自自变量列表：{', '.join(invalid_cat)}[/red]")
        raise typer.Exit(code=1)

    with make_client(server) as client:
        upload_result = client.trial_upload(path)
        if not as_json:
            render_upload_meta(upload_result, console)
            warn_unspecified_categorical(upload_result, x_cols, cat_cols, console)
        token = upload_result.get("upload_token")
        if not token:
            console.print("[red]试用上传响应缺少 upload_token[/red]")
            raise typer.Exit(code=2)

        payload = {
            "upload_token": token,
            "y_col": y,
            "x_cols": list(dict.fromkeys(x_cols)),
            "categorical_cols": list(dict.fromkeys(cat_cols)),
        }

        with console.status("[cyan]分析中…（试用通道为同步计算，小数据集通常几秒内完成）"):
            result = client.trial_analyze(payload)

    if as_json:
        print_json(result)
    else:
        console.print()
        render_trial_report(result, console)
        console.print(
            Panel(
                "[dim]想要最优离散化参数、交互/风险/生态探测器与图表导出？\n"
                "执行 [bold]opgd login[/bold] 后使用 [bold]opgd analyze[/bold] 走正式通道。[/dim]",
                border_style="dim",
                expand=False,
            )
        )
