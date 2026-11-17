"""终端渲染：Rich 表格。

防御式设计：已知字段做美化映射，未知字段动态兜底展示，
上游报告结构增加字段时 CLI 不会崩。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .polling import status_label

# ---------------------------------------------------------------- 字段美化

COLUMN_LABELS = {
    "Factor": "因子",
    "Factor1": "因子 1",
    "Factor2": "因子 2",
    "q-statistic": "q 统计量",
    "q(X1)": "q(X1)",
    "q(X2)": "q(X2)",
    "q(X1∩X2)": "q(X1∩X2)",
    "Interaction": "交互类型",
    "Stratum1": "分层 1",
    "Stratum2": "分层 2",
    "Mean1": "均值 1",
    "Mean2": "均值 2",
    "t-statistic": "t 统计量",
    "p-value": "p 值",
    "p_val": "p 值",
    "Significant": "显著",
    "SSW1": "SSW1",
    "SSW2": "SSW2",
    # fuzzygd 报告特有列
    "method": "方法",
    "bins": "分级数",
    "fuzziness": "模糊系数",
    "engine": "引擎",
    "q_engine": "q 引擎",
    "p_engine": "p 引擎",
    "detector": "探测器",
}

INTERACTION_LABELS = {
    # 服务端 _interaction_type_v2 实际枚举
    "Nonlinear-weaken": "非线性减弱",
    "Uni-weaken": "单因子减弱",
    "Bi-enhance": "双因子增强",
    "Independent": "相互独立",
    "Nonlinear-enhance": "非线性增强",
    # 兼容其他常见命名
    "nonlinearity_enhanced": "非线性增强",
    "nonlinearity_weakened": "非线性减弱",
    "bifactor_enhanced": "双因子增强",
    "independent": "相互独立",
    "single_factor_weakened_nonlinear": "单因子减弱非线性",
    "enhance_bivariate": "双因子增强",
    "enhance_monofactor": "单因子增强",
    "weaken_nonlinear": "非线性减弱",
}

METHOD_ZH = {
    "equal_interval": "等间距",
    "quantile": "分位数",
    "natural_breaks": "自然断点",
    "geometric": "几何间隔",
    "std_mean": "均值标准差",
    "kmeans": "K-Means",
    "rgd": "RGD",
    "categorical": "分类变量",
}


def fmt_value(value: Any) -> str:
    """数值格式化：浮点保留 4 位小数，布尔转 ✓/✗，None 转 -。"""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "[green]是[/green]" if value else "[red]否[/red]"
    if value == "Yes":
        return "[green]是[/green]"
    if value == "No":
        return "[dim]否[/dim]"
    if isinstance(value, float):
        if value != value:  # NaN
            return "-"
        return f"{value:.4f}".rstrip("0").rstrip(".") if abs(value) < 1e6 else f"{value:.3e}"
    return str(value)


def _make_table(title: str, columns: Sequence[str], *, box_style=box.SIMPLE_HEAVY) -> Table:
    table = Table(title=f"[bold]{title}[/bold]", box=box_style, title_justify="left", pad_edge=False)
    for col in columns:
        table.add_column(col, overflow="fold")
    return table


def _records_table(title: str, records: List[Dict[str, Any]], *, max_rows: int = 100) -> Optional[Table]:
    """从 list[dict] 动态建表，空记录返回 None。"""
    if not records:
        return None
    columns: List[str] = []
    for row in records[:20]:
        for key in row.keys():
            if key not in columns:
                columns.append(key)
    table = _make_table(title, [COLUMN_LABELS.get(c, c) for c in columns])
    for row in records[:max_rows]:
        cells = []
        for key in columns:
            value = row.get(key)
            if key == "Interaction":
                label = INTERACTION_LABELS.get(str(value), str(value))
                color = "green" if "增强" in label else ("yellow" if "减弱" in label else "dim")
                cells.append(f"[{color}]{label}[/{color}]")
            elif key in ("Significant",):
                cells.append(fmt_value(value))
            else:
                cells.append(fmt_value(value))
        table.add_row(*cells)
    if len(records) > max_rows:
        table.caption = f"（仅显示前 {max_rows} 条，共 {len(records)} 条）"
    return table


# ---------------------------------------------------------------- 上传元数据

def warn_unspecified_categorical(upload: Dict[str, Any], x_cols: List[str], cat_cols: List[str], console: Console) -> None:
    """上传响应里检测到文本型自变量但用户未声明 --cat 时给出提醒。"""
    columns = upload.get("columns") or []
    suspicious = [
        col.get("name")
        for col in columns
        if col.get("name") in x_cols
        and col.get("name") not in cat_cols
        and (col.get("inferred_role") == "categorical" or col.get("dtype") == "object")
    ]
    if suspicious:
        console.print(
            f"[yellow]⚠ 检测到疑似分类变量未声明：{', '.join(map(str, suspicious))}\n"
            f"  文本列需通过 --cat 声明，否则服务端按数值处理可能导致有效样本清零。[/yellow]"
        )


def render_upload_meta(upload: Dict[str, Any], console: Console) -> None:
    """展示上传响应：文件信息 + 列推荐表。"""
    name = upload.get("original_filename") or upload.get("filename", "?")
    rows = upload.get("row_count") or upload.get("effective_rows", "?")
    cols = upload.get("column_count") or upload.get("effective_columns")
    n_cols = len(cols) if isinstance(cols, list) else (upload.get("column_count") or "?")
    size = upload.get("file_size") or upload.get("accepted_file_size")
    size_text = f"，{size / 1024:.1f} KB" if isinstance(size, (int, float)) else ""

    console.print(
        Panel(
            f"[bold]{name}[/bold]  ·  {rows} 行 × {n_cols} 列{size_text}",
            title="上传成功",
            border_style="green",
            expand=False,
        )
    )
    upload_id = upload.get("id") or upload.get("upload_id")
    token = upload.get("upload_token")
    if upload_id is not None:
        console.print(f"upload_id: [bold cyan]{upload_id}[/bold cyan]（analyze 时可用 --upload-id 复用）")
    if token:
        console.print(f"upload_token: [bold cyan]{token}[/bold cyan]")

    columns = upload.get("columns") or []
    if columns:
        table = _make_table("列元数据与服务端推荐", ["列名", "类型", "缺失率", "唯一值", "推荐Y", "可用X"])
        for col in columns:
            table.add_row(
                str(col.get("name", "?")),
                str(col.get("dtype", "?")),
                f"{col.get('missing_ratio', 0):.1%}" if isinstance(col.get("missing_ratio"), (int, float)) else "-",
                str(col.get("unique_count", "-")),
                "[bold green]★[/bold green]" if col.get("is_recommended_y") else "",
                "[green]✓[/green]" if col.get("is_recommended_x", True) else "[dim]✗[/dim]",
            )
        console.print(table)
        console.print("[dim]提示：★ 为服务端推荐的因变量 Y；后续 analyze 命令需指定 -y 与 -x[/dim]")


# ---------------------------------------------------------------- 试用通道报告

def render_trial_report(resp: Dict[str, Any], console: Console) -> None:
    """渲染免费试用通道的同步分析结果。"""
    title = resp.get("title") or "OPGD 免费试用分析"
    console.print(Panel(f"[bold]{title}[/bold]", border_style="cyan", expand=False))
    console.print(f"task_id: [cyan]{resp.get('task_id', '-')}[/cyan]")

    # 应用配置
    config = resp.get("applied_config") or {}
    if config:
        methods = [METHOD_ZH.get(m, m) for m in config.get("methods") or []]
        console.print(
            f"配置：Y=[bold]{config.get('y_col', '-')}[/bold]  "
            f"X=[bold]{', '.join(config.get('x_cols') or [])}[/bold]  "
            f"分级={config.get('min_bins', '?')}~{config.get('max_bins', '?')}  "
            f"方法={', '.join(methods) or '-'}"
        )

    # 数据集摘要
    summary = resp.get("dataset_summary") or {}
    if summary:
        console.print(
            f"数据：{summary.get('original_filename', '-')}，"
            f"有效行 {summary.get('effective_rows', '-')}"
            + ("，[yellow]数据已被截断[/yellow]" if summary.get("truncated") else "")
        )

    # 因子探测器
    table = _records_table("因子探测器（q 值排序）", resp.get("factor_detector_q_values") or [])
    if table:
        console.print(table)
        console.print("[dim]注：免费体验版仅提供因子探测器结果，其余模块在正式版开放。[/dim]")

    # 被遮罩的模块提示
    masked = resp.get("masked_modules") or {}
    visible_masked = {k: v for k, v in masked.items() if isinstance(v, dict) and not v.get("visible", False)}
    if visible_masked:
        console.print()
        for module, info in visible_masked.items():
            console.print(f"[yellow]🔒[/yellow] {info.get('mask_title', module)} —— {info.get('mask_desc', '')}")


# ---------------------------------------------------------------- 正式通道报告

def _render_optimal_params(params: Dict[str, Any], console: Console) -> None:
    if not params:
        return
    # 形态一：按变量分组 {X1: {method, bins, q_value}, ...}
    per_variable = all(isinstance(v, dict) for v in params.values()) and params
    if per_variable:
        table = _make_table("最优离散化参数（按变量）", ["变量", "最优方法", "分级数", "q 值"])
        for var, info in params.items():
            method = info.get("method") or info.get("best_method") or "-"
            table.add_row(
                str(var),
                METHOD_ZH.get(method, str(method)),
                str(info.get("bins", info.get("best_bins", "-"))),
                fmt_value(info.get("q_value")),
            )
        console.print(table)
        return
    # 形态二：扁平 {method, bins, ...}
    lines = []
    method = params.get("method") or params.get("best_method")
    bins = params.get("bins") or params.get("best_bins")
    if method:
        lines.append(f"最优方法：[bold]{METHOD_ZH.get(method, method)}[/bold]")
    if bins is not None:
        lines.append(f"最优分级：[bold]{bins}[/bold]")
    for key, value in params.items():
        if key in ("method", "best_method", "bins", "best_bins", "chart", "chart_spec"):
            continue
        if isinstance(value, (str, int, float, bool)):
            lines.append(f"{key}: {fmt_value(value)}")
    if lines:
        console.print(_make_panel_group("最优离散化参数", lines))


def _make_panel_group(title: str, lines: List[str]) -> Panel:
    return Panel("\n".join(lines), title=f"[bold]{title}[/bold]", border_style="blue", expand=False)


def _render_interaction_matrix(payload: Dict[str, Any], console: Console) -> None:
    """交互探测器：优先渲染 pairs 表，附带矩阵视图。"""
    factors = payload.get("factors") or []
    matrix = payload.get("matrix") or []
    pairs = payload.get("pairs") or []

    if matrix and factors:
        table = Table(title="[bold]交互探测器 · q(X1∩X2) 矩阵[/bold]", box=box.SIMPLE_HEAVY, title_justify="left")
        table.add_column("", justify="right")
        for f in factors:
            table.add_column(str(f), justify="center")
        by_factor = {row.get("factor"): row.get("values") or [] for row in matrix}
        for i, f in enumerate(factors):
            values = by_factor.get(f, [])
            cells = []
            for j in range(len(factors)):
                v = values[j] if j < len(values) else None
                cells.append("-" if (v is None or j >= i) else fmt_value(v))
            table.add_row(f"[bold]{f}[/bold]", *cells)
        console.print(table)

    if pairs:
        table = _records_table("交互探测器 · 因子两两组合", pairs)
        if table:
            console.print(table)


def render_full_report(report: Dict[str, Any], console: Console) -> None:
    """渲染正式通道完整报告。"""
    title = report.get("title") or "OPGD 分析报告"
    console.print(Panel(f"[bold]{title}[/bold]", border_style="cyan", expand=False))

    # 摘要行
    summary = report.get("summary") or {}
    bits = []
    if summary.get("top_factor"):
        bits.append(f"主导因子 [bold]{summary['top_factor']}[/bold]（q={fmt_value(summary.get('top_q_value'))}）")
    if summary.get("significant_factor_count") is not None:
        bits.append(f"显著因子 {summary['significant_factor_count']} 个")
    if report.get("runtime_ms"):
        bits.append(f"耗时 {report['runtime_ms'] / 1000:.1f}s")
    status = report.get("status")
    if status:
        bits.append(f"状态 {status_label(status)}")
    if bits:
        console.print(" · ".join(bits))

    _render_optimal_params(report.get("optimal_params") or {}, console)

    # 四大探测器
    factor = report.get("factor_detector")
    if isinstance(factor, list):
        table = _records_table("因子探测器", factor)
        if table:
            console.print(table)
    elif isinstance(factor, dict):
        table = _records_table("因子探测器", factor.get("records") or [])
        if table:
            console.print(table)

    interaction = report.get("interaction_detector")
    if isinstance(interaction, dict) and (interaction.get("pairs") or interaction.get("matrix")):
        _render_interaction_matrix(interaction, console)
    elif isinstance(interaction, dict):
        # 有些版本直接是 {因子: {...}} 形式，兜底按 records 处理
        table = _records_table("交互探测器", interaction.get("records") or [])
        if table:
            console.print(table)

    risk = report.get("risk_detector")
    if isinstance(risk, dict):
        records = risk.get("records")
        if records is None:
            # {col: {means, comparisons}} 形式 → 拍平
            flat: List[Dict[str, Any]] = []
            for col, payload in risk.items():
                if not isinstance(payload, dict):
                    continue
                comparisons = payload.get("comparisons") or []
                if isinstance(comparisons, dict):
                    comparisons = comparisons.get("records") or []
                for comp in comparisons:
                    if isinstance(comp, dict):
                        flat.append({"因子": col, **comp})
            records = flat
        table = _records_table("风险探测器（分层均值差异 t 检验）", records or [], max_rows=30)
        if table:
            console.print(table)

    ecological = report.get("ecological_detector")
    if isinstance(ecological, list):
        table = _records_table("生态探测器（F 检验）", ecological)
        if table:
            console.print(table)
    elif isinstance(ecological, dict):
        records = ecological.get("records") or (ecological if all(isinstance(v, dict) for v in ecological.values()) and ecological else None)
        table = _records_table("生态探测器（F 检验）", records or [])
        if table:
            console.print(table)

    console.print(f"[dim]报告 task_id：{report.get('id') or report.get('task_id', '-')}[/dim]")


# ---------------------------------------------------------------- 任务列表

def render_task_list(tasks: List[Dict[str, Any]], console: Console) -> None:
    if not tasks:
        console.print("[dim]暂无任务[/dim]")
        return
    table = _make_table("分析任务", ["任务 ID", "标题", "状态", "模型", "Y", "X", "创建时间"])
    for task in tasks:
        input_summary = task.get("input_summary") or {}
        created = (task.get("created_at") or "")[:19].replace("T", " ")
        status = task.get("status", "?")
        color = {"SUCCESS": "green", "FAILED": "red", "PROCESSING": "yellow", "PENDING": "dim"}.get(status, "white")
        table.add_row(
            task.get("task_id", "?"),
            str(input_summary.get("title") or "-")[:32],
            f"[{color}]{status_label(status)}[/{color}]",
            input_summary.get("analysis_model") or "opgd",
            str(input_summary.get("y_col") or "-"),
            ", ".join(input_summary.get("x_cols") or [])[:40],
            created,
        )
    console.print(table)


def render_task_status(task: Dict[str, Any], console: Console) -> None:
    status = task.get("status", "?")
    color = {"SUCCESS": "green", "FAILED": "red", "PROCESSING": "yellow", "PENDING": "dim"}.get(status, "white")
    console.print(f"任务 [cyan]{task.get('task_id', '?')}[/cyan]  状态：[{color}]{status_label(status)}[/{color}]")
    input_summary = task.get("input_summary") or {}
    if input_summary:
        console.print(
            f"  Y=[bold]{input_summary.get('y_col', '-')}[/bold]  "
            f"X={', '.join(input_summary.get('x_cols') or []) or '-'}  "
            f"模型={input_summary.get('analysis_model') or 'opgd'}"
        )
    if task.get("error"):
        console.print(f"  [red]错误：{task['error']}[/red]")
    if task.get("result") and task.get("status") == "SUCCESS":
        console.print("  [green]✔ 分析完成，可执行 opgd report <task_id> 查看报告[/green]")
