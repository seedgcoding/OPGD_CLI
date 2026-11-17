"""render.py 渲染测试：防御式行为与美化映射。"""

from __future__ import annotations

from rich.console import Console

from opgd_cli.render import (
    fmt_value,
    render_full_report,
    render_task_list,
    render_trial_report,
    render_upload_meta,
)
from .conftest import SAMPLE_FULL_REPORT, SAMPLE_TASK_SUCCESS, SAMPLE_TRIAL_REPORT, SAMPLE_UPLOAD


def make_console() -> Console:
    return Console(record=True, width=120, force_terminal=False, no_color=True)


def render_to_text(func, *args) -> str:
    console = make_console()
    with console.capture() as capture:
        func(*args, console)
    return capture.get()


def test_fmt_value():
    """fmt_value 返回 Rich markup（用于表格单元格）。"""
    assert fmt_value(None) == "-"
    assert "是" in fmt_value(True)
    assert "是" in fmt_value("Yes")
    assert "否" in fmt_value(False)
    assert fmt_value(0.12345) == "0.1235"
    assert fmt_value(float("nan")) == "-"


def test_render_upload_meta():
    text = render_to_text(render_upload_meta, SAMPLE_UPLOAD)
    assert "sample.csv" in text
    assert "40 行" in text
    assert "X1" in text and "GDP" in text
    assert "推荐Y" in text


def test_render_upload_meta_missing_fields():
    """防御式：字段缺失不崩。"""
    text = render_to_text(render_upload_meta, {})
    assert "上传成功" in text


def test_render_trial_report():
    text = render_to_text(render_trial_report, SAMPLE_TRIAL_REPORT)
    assert "免费体验版因子探测结果" in text
    assert "0.876" in text
    assert "交互探测结果已生成" in text


def test_render_full_report_all_detectors():
    text = render_to_text(render_full_report, SAMPLE_FULL_REPORT)
    assert "因子探测器" in text
    assert "交互探测器" in text
    assert "非线性增强" in text
    assert "风险探测器" in text
    assert "生态探测器" in text
    assert "X1" in text


def test_render_full_report_defensive():
    """未知字段/空报告不崩。"""
    text = render_to_text(render_full_report, {"title": "空报告"})
    assert "空报告" in text
    text2 = render_to_text(render_full_report, {})
    assert isinstance(text2, str)


def test_render_full_report_risk_flat_mapping():
    """risk_detector 为 {col: {comparisons}} 旧结构时可拍平渲染。"""
    report = {
        "title": "R",
        "risk_detector": {"X1": {"comparisons": [{"Stratum1": 1, "Stratum2": 2, "Significant": "Yes"}]}},
    }
    text = render_to_text(render_full_report, report)
    assert "风险探测器" in text
    assert "X1" in text


def test_render_task_list():
    text = render_to_text(render_task_list, [SAMPLE_TASK_SUCCESS])
    assert "task-1" in text
    assert "完成" in text
    text2 = render_to_text(render_task_list, [])
    assert "暂无任务" in text2


def test_warn_unspecified_categorical():
    from opgd_cli.render import warn_unspecified_categorical

    upload = {"columns": [
        {"name": "X1", "dtype": "float64", "inferred_role": "numeric"},
        {"name": "X3", "dtype": "object", "inferred_role": "categorical"},
    ]}
    console = make_console()
    with console.capture() as capture:
        warn_unspecified_categorical(upload, ["X1", "X3"], [], console)
    text = capture.get()
    assert "X3" in text and "--cat" in text

    # 已声明则不告警
    console2 = make_console()
    with console2.capture() as capture2:
        warn_unspecified_categorical(upload, ["X1", "X3"], ["X3"], console2)
    assert "--cat" not in capture2.get()


def test_optimal_params_per_variable():
    """optimal_params 按变量分组形态的渲染。"""
    report = {
        "title": "R",
        "optimal_params": {
            "X1": {"method": "natural_breaks", "bins": 8, "q_value": 0.84},
            "X3": {"method": "categorical", "bins": 3, "q_value": 0.0006},
        },
    }
    text = render_to_text(render_full_report, report)
    assert "最优离散化参数" in text
    assert "自然断点" in text
    assert "分类变量" in text
    assert "X1" in text
