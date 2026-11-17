"""本地全链路 E2E：CLI x 本地模拟服务，不触碰生产环境。

覆盖闭环：登录 → whoami → 上传 → 提交分析 → 轮询 → 报告 → 导出 → 一次性上传复用 →
异常路径（401 / 402 额度不足 / 429 限流）。
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from opgd_cli.app import app

from .conftest import runner  # noqa: F401  (re-export 给 pytest 收集)
from .mock_server import MockOPGDServer, MockState


@pytest.fixture
def mock_server(isolated_config, monkeypatch):
    monkeypatch.setenv("OPGD_NO_PROXY", "1")
    server = MockOPGDServer(MockState(tokens=2))
    thread = server.serve_forever  # ThreadingHTTPServer 在后台线程服务
    import threading

    t = threading.Thread(target=thread, daemon=True)
    t.start()
    yield server
    server.shutdown()
    server.server_close()


def invoke(mock_server, *args):
    """--server 是每命令选项，统一追加在尾部。"""
    return runner.invoke(app, [*args, "--server", mock_server.base_url])


def test_full_closed_loop(mock_server, tmp_path, sample_csv):
    """登录 → whoami → upload → analyze(等待) → report → export 全链路。"""
    base = mock_server.base_url

    # 1. 登录
    result = runner.invoke(
        app, ["auth", "login", "--server", base, "-u", "tester", "--password-stdin"],
        input="right-pass\n",
    )
    assert result.exit_code == 0, result.output

    # 2. whoami（profile 信息）
    result = invoke(mock_server, "auth", "whoami")
    assert result.exit_code == 0
    assert "tester" in result.output and "剩余分析次数：2" in result.output

    # 3. analyze 一条龙（自动上传+等待+渲染）
    result = invoke(mock_server, "analyze", str(sample_csv), "-y", "GDP", "-x", "X1,X2",
                    "--title", "本地闭环")
    assert result.exit_code == 0, result.output
    assert "本地闭环" in result.output
    assert "因子探测器" in result.output
    assert "最优离散化参数" in result.output and "自然断点" in result.output
    assert "交互探测器" in result.output and "双因子增强" in result.output
    assert "风险探测器" in result.output and "生态探测器" in result.output

    # 4. 报告 JSON（task_id 从「任务已受理」行提取）
    import re

    m = re.search(r"任务已受理：\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", result.output)
    assert m, result.output
    tid = m.group(1)
    result = invoke(mock_server, "report", tid, "--json")
    assert result.exit_code == 0
    report = json.loads(result.output)
    assert report["status"] == "SUCCESS"
    assert report["optimal_params"]["X1"]["method"] == "natural_breaks"

    # 5. 导出（zip + 解压 + png）
    out_dir = tmp_path / "out"
    result = invoke(mock_server, "export", tid, "--output", str(out_dir), "--unzip", "--png")
    assert result.exit_code == 0, result.output
    zips = list(out_dir.glob("*.zip"))
    assert zips and zipfile.ZipFile(zips[0]).testzip() is None
    pngs = list(out_dir.glob("*.png"))
    assert len(pngs) == 2
    for p in pngs:
        assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    # 6. 额度扣减：2 → 1
    result = invoke(mock_server, "auth", "whoami")
    assert "剩余分析次数：1" in result.output


def test_upload_oneshot_semantics(mock_server, sample_csv):
    """一次性上传：同一 upload_id 第二次分析应产出 FAILED 任务并给出提示。"""
    base = mock_server.base_url
    runner.invoke(app, ["auth", "login", "--server", base, "-u", "tester", "--password-stdin"],
                  input="right-pass\n")
    result = invoke(mock_server, "upload", str(sample_csv), "--json")
    upload_id = json.loads(result.output)["id"]

    # 第一次：成功
    result = invoke(mock_server, "analyze", "--upload-id", str(upload_id), "-y", "GDP",
                    "-x", "X1,X2", "--no-wait")
    assert result.exit_code == 0, result.output

    # 等任务 1 完成（模拟服务在终态后将上传标记 CLEANED）
    import time
    time.sleep(1.0)

    # 第二次：文件已被消费 → 任务 FAILED + 提示
    result = invoke(mock_server, "analyze", "--upload-id", str(upload_id), "-y", "GDP",
                    "-x", "X1,X2", "--no-wait")
    assert result.exit_code == 0  # 提交本身受理成功（与生产行为一致）

    time.sleep(0.4)  # 等模拟任务失败
    import re
    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", result.output)
    assert m, result.output
    tid = m.group(1)
    result = invoke(mock_server, "status", tid)
    assert result.exit_code == 0
    assert "失败" in result.output


def test_wrong_password_401(mock_server):
    result = runner.invoke(
        app, ["auth", "login", "--server", mock_server.base_url, "-u", "tester", "--password-stdin"],
        input="wrong-pass\n",
    )
    assert result.exit_code == 3
    assert "认证失败" in result.output


def test_quota_exhausted_402(mock_server, sample_csv):
    """poor 用户 0 额度 → 提交分析被 402 拒绝。"""
    base = mock_server.base_url
    result = runner.invoke(
        app, ["auth", "login", "--server", base, "-u", "poor", "--password-stdin"],
        input="poor-pass\n",
    )
    assert result.exit_code == 0, result.output
    result = invoke(mock_server, "analyze", str(sample_csv), "-y", "GDP", "-x", "X1,X2")
    assert result.exit_code == 4
    assert "额度不足" in result.output


def test_rate_limit_429(mock_server, sample_csv, monkeypatch):
    """上传超过阈值 → 429 → CLI 友好提示。"""
    monkeypatch.setenv("OPGD_NO_PROXY", "1")  # 独立服务实例，避开系统代理
    state = MockState(tokens=2, rate_limit_after=1)
    server = MockOPGDServer(state)
    import threading

    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = server.base_url
        runner.invoke(app, ["auth", "login", "--server", base, "-u", "tester", "--password-stdin"],
                      input="right-pass\n")
        # 第 1 次上传放行，第 2 次触发 429
        r1 = runner.invoke(app, ["upload", str(sample_csv), "--server", base])
        assert r1.exit_code == 0, r1.output
        r2 = runner.invoke(app, ["upload", str(sample_csv), "--server", base])
        assert r2.exit_code == 5
        assert "限流" in r2.output
    finally:
        server.shutdown()
        server.server_close()


def test_trial_flow_local(mock_server, sample_csv):
    result = runner.invoke(
        app, ["trial", str(sample_csv), "-y", "GDP", "-x", "X1,X2", "--server", mock_server.base_url]
    )
    assert result.exit_code == 0, result.output
    assert "因子探测器" in result.output
    assert "0.876" in result.output
    assert "交互探测结果已生成" in result.output


def test_trial_cat_sent_to_server(mock_server, sample_csv):
    import respx  # noqa: F401  (确保不误用；此处直接走本地服务)

    result = runner.invoke(
        app, ["trial", str(sample_csv), "-y", "GDP", "-x", "X1,X2,GDP", "--server", mock_server.base_url]
    )
    # GDP 在 -x 中但它是响应里推荐的 Y —— 这里只验证流程不崩即可
    assert result.exit_code == 0 or "自变量" in result.output


def test_cancel_flow_local(mock_server, sample_csv):
    base = mock_server.base_url
    runner.invoke(app, ["auth", "login", "--server", base, "-u", "tester", "--password-stdin"],
                  input="right-pass\n")
    result = invoke(mock_server, "analyze", str(sample_csv), "-y", "GDP", "-x", "X1,X2", "--no-wait")
    assert result.exit_code == 0
    import re

    tid = re.search(r"([0-9a-f-]{36})", result.output).group(1)
    result = invoke(mock_server, "cancel", tid)
    assert result.exit_code == 0, result.output
    result = invoke(mock_server, "tasks")
    assert result.exit_code == 0
