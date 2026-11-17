"""CLI 命令流程测试：trial / analyze / status / tasks（respx 模拟全部端点）。"""

from __future__ import annotations

import httpx
import pytest
import respx
from typer.testing import CliRunner

from opgd_cli.app import app
from opgd_cli.config import save_auth

from .conftest import (
    SAMPLE_FULL_REPORT,
    SAMPLE_TASK_PENDING,
    SAMPLE_TASK_SUCCESS,
    SAMPLE_TRIAL_REPORT,
    SAMPLE_UPLOAD,
    runner,
)

BASE = "https://opgd500.kkbvip.top"
API = BASE + "/api/v1"


@respx.mock
def test_trial_full_flow(isolated_config, sample_csv):
    respx.post(API + "/opgd/free-trial/uploads").mock(return_value=httpx.Response(200, json=SAMPLE_UPLOAD))
    respx.post(API + "/opgd/free-trial/analyze").mock(
        return_value=httpx.Response(200, json=SAMPLE_TRIAL_REPORT)
    )
    result = runner.invoke(app, ["trial", str(sample_csv), "-y", "GDP", "-x", "X1,X2"])
    assert result.exit_code == 0, result.output
    assert "上传成功" in result.output
    assert "upload_token" in result.output
    assert "因子探测器" in result.output
    assert "0.876" in result.output
    assert "交互探测结果已生成" in result.output


@respx.mock
def test_trial_y_in_x_rejected(isolated_config, sample_csv):
    result = runner.invoke(app, ["trial", str(sample_csv), "-y", "GDP", "-x", "GDP,X1"])
    assert result.exit_code == 1
    assert "不能同时作为自变量" in result.output


@respx.mock
def test_analyze_requires_login(isolated_config, sample_csv):
    result = runner.invoke(app, ["analyze", str(sample_csv), "-y", "GDP", "-x", "X1"])
    assert result.exit_code == 7
    assert "尚未登录" in result.output


@respx.mock
def test_analyze_no_wait_flow(isolated_config, sample_csv):
    save_auth(BASE, "token-abc", "bearer", "tester")
    upload_route = respx.post(API + "/opgd/uploads").mock(
        return_value=httpx.Response(200, json={**SAMPLE_UPLOAD, "id": 42})
    )
    analyze_route = respx.post(API + "/opgd/analyze").mock(
        return_value=httpx.Response(202, json={"task_id": "task-9", "status": "PENDING",
                                               "message": "ok", "remaining_quota": 3})
    )
    result = runner.invoke(
        app, ["analyze", str(sample_csv), "-y", "GDP", "-x", "X1", "-x", "X2", "--no-wait"]
    )
    assert result.exit_code == 0, result.output
    assert "task-9" in result.output
    assert "3" in result.output  # 剩余额度
    sent = __import__("json").loads(analyze_route.calls.last.request.content)
    assert sent["upload_id"] == 42 and sent["y_col"] == "GDP" and sent["x_cols"] == ["X1", "X2"]
    assert upload_route.called


@respx.mock
def test_analyze_rejects_cat_outside_x(isolated_config, sample_csv):
    save_auth(BASE, "token-abc")
    result = runner.invoke(app, ["analyze", str(sample_csv), "-y", "GDP", "-x", "X1", "-c", "X2"])
    assert result.exit_code == 1
    assert "类型变量必须来自自变量列表" in result.output


@respx.mock
def test_status_command(isolated_config):
    save_auth(BASE, "token-abc")
    respx.get(API + "/tasks/task-1").mock(return_value=httpx.Response(200, json=SAMPLE_TASK_SUCCESS))
    result = runner.invoke(app, ["status", "task-1"])
    assert result.exit_code == 0
    assert "task-1" in result.output and "完成" in result.output


@respx.mock
def test_status_json_output(isolated_config):
    save_auth(BASE, "token-abc")
    respx.get(API + "/tasks/task-1").mock(return_value=httpx.Response(200, json=SAMPLE_TASK_PENDING))
    result = runner.invoke(app, ["status", "task-1", "--json"])
    assert result.exit_code == 0
    assert '"PENDING"' in result.output


@respx.mock
def test_tasks_list(isolated_config):
    save_auth(BASE, "token-abc")
    respx.get(API + "/tasks").mock(return_value=httpx.Response(200, json=[SAMPLE_TASK_SUCCESS]))
    result = runner.invoke(app, ["tasks"])
    assert result.exit_code == 0
    assert "task-1" in result.output


@respx.mock
def test_cancel(isolated_config):
    save_auth(BASE, "token-abc")
    route = respx.post(API + "/opgd/tasks/task-1/cancel").mock(return_value=httpx.Response(200, json={}))
    result = runner.invoke(app, ["cancel", "task-1"])
    assert result.exit_code == 0
    assert route.called


@respx.mock
def test_report_renders_full(isolated_config):
    save_auth(BASE, "token-abc")
    respx.get(API + "/opgd/tasks/task-1/report").mock(
        return_value=httpx.Response(200, json=SAMPLE_FULL_REPORT)
    )
    result = runner.invoke(app, ["report", "task-1"])
    assert result.exit_code == 0, result.output
    assert "因子探测器" in result.output
    assert "交互探测器" in result.output
    assert "非线性增强" in result.output
    assert "风险探测器" in result.output
    assert "生态探测器" in result.output
    assert "最优方法" in result.output and "分位数" in result.output  # 最优参数（中文美化）


@respx.mock
def test_export_downloads_zip(isolated_config, tmp_path):
    save_auth(BASE, "token-abc")
    import zipfile
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("report.html", "<h1>ok</h1>")
    respx.get(API + "/opgd/tasks/task-1/export").mock(
        return_value=httpx.Response(
            200, content=buf.getvalue(),
            headers={"Content-Disposition": "attachment; filename=\"opgd_report_task-1.zip\""},
        )
    )
    out_dir = tmp_path / "out"
    result = runner.invoke(app, ["export", "task-1", "--output", str(out_dir), "--unzip"])
    assert result.exit_code == 0, result.output
    assert (out_dir / "opgd_report_task-1.zip").exists()
    assert (out_dir / "opgd_report_task-1" / "report.html").exists()


@respx.mock
def test_401_prompts_relogin(isolated_config):
    save_auth(BASE, "expired-token")
    respx.get(API + "/tasks/task-1").mock(return_value=httpx.Response(401, json={"detail": "过期"}))
    result = runner.invoke(app, ["status", "task-1"])
    assert result.exit_code == 3
    assert "认证失败" in result.output and "opgd login" in result.output


@respx.mock
def test_trial_cat_declaration(isolated_config, sample_csv):
    """trial 支持 --cat，且 --methods/--bins 假参数已移除。"""
    analyze_route = respx.post(API + "/opgd/free-trial/analyze").mock(
        return_value=httpx.Response(200, json=SAMPLE_TRIAL_REPORT)
    )
    respx.post(API + "/opgd/free-trial/uploads").mock(return_value=httpx.Response(200, json=SAMPLE_UPLOAD))
    result = runner.invoke(app, ["trial", str(sample_csv), "-y", "GDP", "-x", "X1,X2", "--cat", "X2"])
    assert result.exit_code == 0, result.output
    sent = __import__("json").loads(analyze_route.calls.last.request.content)
    assert sent["categorical_cols"] == ["X2"]


@respx.mock
def test_doctor_all_pass(isolated_config):
    save_auth(BASE, "token-abc")
    respx.get(API + "/health").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"status": "healthy",
                                                                     "service": "OPGD", "version": "1.0.0"}})
    )
    respx.get(API + "/profile/").mock(
        return_value=httpx.Response(200, json={"username": "tester", "role_label": "普通用户",
                                               "remaining_quota": 3, "consumed_count": 2})
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "全部通过" in result.output
    assert "tester" in result.output


@respx.mock
def test_doctor_reports_expired(isolated_config):
    respx.get(API + "/health").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"status": "healthy"}})
    )
    respx.get(API + "/profile/").mock(return_value=httpx.Response(401, json={"detail": "过期"}))
    save_auth(BASE, "expired")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "opgd auth login" in result.output
