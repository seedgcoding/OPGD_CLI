"""上传命令。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from ..runtime import print_json
from ..runtime import SERVER_OPTION, console, handle_errors, make_client
from ..render import render_upload_meta
from ..utils import validate_upload_file

app = typer.Typer(help="上传数据文件", no_args_is_help=True)


@app.command()
@handle_errors
def upload(
    file: Path = typer.Argument(..., exists=True, readable=True, help="CSV/Excel 数据文件（≤50MB）"),
    server: Optional[str] = SERVER_OPTION,
    as_json: bool = typer.Option(False, "--json", help="以原始 JSON 输出"),
) -> None:
    """上传数据文件到正式通道，展示列元数据与服务端角色推荐。"""
    path = validate_upload_file(file)
    with make_client(server) as client:
        result = client.upload(path)
    if as_json:
        print_json(result)
    else:
        render_upload_meta(result, console)
