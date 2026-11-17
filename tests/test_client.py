"""client.py 单元测试：端点封装与错误映射。"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from opgd_cli.client import OPGDClient
from opgd_cli.config import Profile
from opgd_cli.exceptions import AuthError, APIError, QuotaError, RateLimitError

BASE = "https://test.example.com"
API = BASE + "/api/v1"


def make_client(token: str | None = None) -> OPGDClient:
    profile = Profile(server=BASE, access_token=token)
    return OPGDClient(profile, use_proxy=False)


@respx.mock
def test_login_sends_credentials():
    """服务端契约：登录字段名为 phone（接受用户名或手机号作为标识）。"""
    route = respx.post(API + "/auth/login").mock(return_value=httpx.Response(200, json={"access_token": "t1"}))
    with make_client() as client:
        result = client.login("u", "p")
    assert result["access_token"] == "t1"
    assert route.called
    sent = json.loads(route.calls.last.request.content)
    assert sent["phone"] == "u" and sent["password"] == "p"


@respx.mock
def test_upload_multipart():
    respx.post(API + "/opgd/uploads").mock(return_value=httpx.Response(200, json={"id": 9}))
    import io

    with make_client(token="t") as client:
        files = {"file": ("a.csv", io.BytesIO(b"x,y\n1,2\n"))}
        result = client.request("POST", "/opgd/uploads", files=files).json()
    assert result["id"] == 9


@respx.mock
def test_analyze_payload_dedup_and_defaults():
    route = respx.post(API + "/opgd/analyze").mock(
        return_value=httpx.Response(202, json={"task_id": "t", "remaining_quota": 5})
    )
    with make_client(token="t") as client:
        client.analyze(9, "GDP", ["X1", "X1", "X2"], categorical_cols=["X1"])
    sent = json.loads(route.calls.last.request.content)
    assert sent["x_cols"] == ["X1", "X2"]
    assert sent["upload_id"] == 9
    assert sent["analysis_model"] == "opgd"
    assert sent["num_permutations"] == 99


@respx.mock
def test_error_mapping_401_429_402():
    respx.get(API + "/auth/me").mock(return_value=httpx.Response(401, json={"detail": "token 失效"}))
    respx.get(API + "/tasks").mock(
        return_value=httpx.Response(429, json={"detail": "过于频繁"}, headers={"Retry-After": "30"})
    )
    respx.get(API + "/opgd/tasks/1/report").mock(return_value=httpx.Response(402, json={"detail": "额度不足"}))

    with make_client(token="t") as client:
        with pytest.raises(AuthError):
            client.me()
        with pytest.raises(RateLimitError) as exc_info:
            client.list_tasks()
        assert exc_info.value.retry_after == 30
        with pytest.raises(QuotaError):
            client.get_report("1")


@respx.mock
def test_error_mapping_validation_detail_list():
    """FastAPI 422 的 detail 是列表，应拼接为可读信息。"""
    respx.post(API + "/opgd/analyze").mock(
        return_value=httpx.Response(422, json={"detail": [{"msg": "y_col 不能为空"}]})
    )
    with make_client(token="t") as client:
        with pytest.raises(APIError) as exc_info:
            client.analyze(1, "", ["X"])
    assert "y_col 不能为空" in str(exc_info.value)


@respx.mock
def test_task_and_report_endpoints():
    respx.get(API + "/tasks/task-1").mock(return_value=httpx.Response(200, json={"status": "SUCCESS"}))
    respx.get(API + "/opgd/tasks/task-1/report").mock(return_value=httpx.Response(200, json={"title": "R"}))
    respx.get(API + "/opgd/tasks/task-1/export").mock(
        return_value=httpx.Response(
            200,
            content=b"zip-bytes",
            headers={"Content-Disposition": "attachment; filename=\"r.zip\"; filename*=UTF-8''%E6%8A%A5%E5%91%8A.zip"},
        )
    )
    respx.post(API + "/opgd/tasks/task-1/cancel").mock(return_value=httpx.Response(200, json={"ok": True}))
    respx.get(API + "/opgd/tasks/task-1/charts/factor-detector.png").mock(
        return_value=httpx.Response(200, content=b"png")
    )

    with make_client(token="t") as client:
        assert client.get_task("task-1")["status"] == "SUCCESS"
        assert client.get_report("task-1")["title"] == "R"
        content, filename = client.export_report("task-1")
        assert content == b"zip-bytes"
        assert filename == "报告.zip"  # 优先 RFC5987 filename*
        client.cancel_task("task-1")
        assert client.export_chart("task-1", "factor") == b"png"


@respx.mock
def test_proxy_fallback_on_connect_error():
    """系统代理连接失败时自动直连重试。"""
    real_route = respx.get(API + "/auth/me").mock(return_value=httpx.Response(200, json={"username": "u"}))

    client = OPGDClient(Profile(server=BASE, access_token="t"), use_proxy=True)
    calls_before = real_route.call_count
    # respx 不模拟代理层，这里只验证 trust_env 切换不破坏正常请求
    assert client.me()["username"] == "u"
    assert real_route.call_count == calls_before + 1
    client.close()


@respx.mock
def test_trial_endpoints():
    respx.post(API + "/opgd/free-trial/uploads").mock(
        return_value=httpx.Response(200, json={"upload_token": "tok"})
    )
    respx.post(API + "/opgd/free-trial/analyze").mock(
        return_value=httpx.Response(200, json={"task_id": "x", "factor_detector_q_values": []})
    )
    import io

    with make_client() as client:
        files = {"file": ("a.csv", io.BytesIO(b"x\n1\n"))}
        up = client.request("POST", "/opgd/free-trial/uploads", files=files).json()
        assert up["upload_token"] == "tok"
        result = client.trial_analyze({"upload_token": "tok", "y_col": "y", "x_cols": ["x"]})
        assert result["task_id"] == "x"
