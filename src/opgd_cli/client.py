"""OPGD 平台 HTTP 客户端。

纯客户端实现：只调用线上 REST API，不依赖任何服务端代码。
端点契约依据线上 ``/api/v1`` OpenAPI（36 paths，2026-11 抓取）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from .config import Profile
from .exceptions import APIError, AuthError, QuotaError, RateLimitError

API_PREFIX = "/api/v1"

# 上传文件较大时读响应可能较慢，给足超时
DEFAULT_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=300.0, pool=30.0)

DEFAULT_METHODS = ["equal_interval", "quantile", "natural_breaks", "geometric", "std_mean"]
OPGD_METHODS = DEFAULT_METHODS
FUZZYGD_METHODS = ["equal_interval", "quantile", "natural_breaks", "geometric", "kmeans", "rgd"]

CHART_ENDPOINTS = {
    "factor": "factor-detector.png",
    "interaction": "interaction-detector.png",
}


def _map_status_error(response: httpx.Response) -> APIError:
    status = response.status_code
    retry_after = response.headers.get("Retry-After")
    retry_secs = int(retry_after) if retry_after and retry_after.isdigit() else None
    try:
        detail = response.json().get("detail", response.text)
    except Exception:
        detail = response.text

    if status in (401, 403):
        return AuthError(status, detail)
    if status == 429:
        return RateLimitError(status, detail, retry_after=retry_secs)
    if status == 402 or (isinstance(detail, str) and ("额度" in detail or "quota" in detail.lower())):
        return QuotaError(status, detail)
    return APIError(status, detail)


class OPGDClient:
    """同步 HTTP 客户端，命令层直接持有使用。

    连接失败时若走了系统代理，自动改为直连重试一次
    （本机代理对部分域名不可达是常见环境，curl 不受影响而 Python 受影响）。
    """

    def __init__(self, profile: Profile, *, timeout: httpx.Timeout = DEFAULT_TIMEOUT, use_proxy: bool = True):
        self._profile = profile
        self.server = profile.server.rstrip("/")
        self._timeout = timeout
        self._use_proxy = use_proxy
        self._proxy_notice_shown = False
        headers = {
            "User-Agent": "opgd-cli/0.1",
            "Accept": "application/json",
        }
        auth_header = profile.auth_header
        if auth_header:
            headers.update(auth_header)
        self._headers = headers
        self._http = self._build_client(trust_env=use_proxy)

    def _build_client(self, *, trust_env: bool) -> httpx.Client:
        return httpx.Client(
            base_url=self.server,
            headers=self._headers,
            timeout=self._timeout,
            follow_redirects=True,
            trust_env=trust_env,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "OPGDClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ------------------------------------------------------------------ 底层

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = self._http.request(method, API_PREFIX + path, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            if not self._use_proxy or self._proxy_notice_shown:
                raise
            # 系统代理不可达 → 自动直连重试一次，并记住该结论
            self._http.close()
            self._http = self._build_client(trust_env=False)
            self._proxy_notice_shown = True
            import sys

            print(
                f"[opgd] 系统代理不可达，本次已改用直连（结论将记住，可用 OPGD_NO_PROXY=0 恢复代理）：{exc}",
                file=sys.stderr,
            )
            response = self._http.request(method, API_PREFIX + path, **kwargs)
            try:
                self._remember_direct_mode()
            except Exception:
                pass
        if response.is_error:
            raise _map_status_error(response)
        return response

    def _remember_direct_mode(self) -> None:
        """把"该服务端直连更稳"写入配置，后续命令直接跳过代理。"""
        from .config import load_config, save_config

        data = load_config()
        profiles: dict = data.setdefault("profiles", {})
        entry: dict = profiles.setdefault(self._profile.name, {})
        entry.setdefault("server", self.server)
        entry["no_proxy"] = True
        save_config(data)

    def get_json(self, path: str, params: Optional[dict] = None) -> Any:
        return self.request("GET", path, params=params).json()

    def post_json(self, path: str, payload: Optional[dict] = None) -> Any:
        return self.request("POST", path, json=payload).json()

    # ------------------------------------------------------------------ 认证

    def login(self, username: str, password: str) -> Dict[str, Any]:
        """POST /auth/login → Token。

        服务端契约：字段名为 ``phone``，但实际接受用户名或手机号作为登录标识。
        """
        return self.request("POST", "/auth/login", json={"phone": username, "password": password}).json()

    def me(self) -> Dict[str, Any]:
        return self.get_json("/auth/me")

    def profile(self) -> Dict[str, Any]:
        """GET /profile → 用户概要（含已用次数、账号状态）。"""
        return self.get_json("/profile/")

    def health(self, detailed: bool = False) -> Dict[str, Any]:
        """GET /health（或 /health/detailed）→ 服务健康状态。"""
        path = "/health/detailed" if detailed else "/health"
        return self.get_json(path)

    # ------------------------------------------------------------------ 上传

    def upload(self, file_path: Path) -> Dict[str, Any]:
        """POST /opgd/uploads（正式通道，需登录）。"""
        return self._upload_to(file_path, "/opgd/uploads")

    def trial_upload(self, file_path: Path) -> Dict[str, Any]:
        """POST /opgd/free-trial/uploads（免登录试用通道）。"""
        return self._upload_to(file_path, "/opgd/free-trial/uploads")

    def _upload_to(self, file_path: Path, path: str) -> Dict[str, Any]:
        file_path = Path(file_path)
        if not file_path.is_file():
            raise FileNotFoundError(f"文件不存在：{file_path}")
        with open(file_path, "rb") as fh:
            files = {"file": (file_path.name, fh)}
            return self.request("POST", path, files=files).json()

    def get_upload(self, upload_id: int) -> Dict[str, Any]:
        return self.get_json(f"/opgd/uploads/{upload_id}")

    # ------------------------------------------------------------------ 分析

    def analyze(
        self,
        upload_id: int,
        y_col: str,
        x_cols: List[str],
        *,
        title: Optional[str] = None,
        analysis_model: str = "opgd",
        categorical_cols: Optional[List[str]] = None,
        methods: Optional[List[str]] = None,
        min_bins: int = 3,
        max_bins: int = 8,
        fuzziness_mode: str = "quick",
        fuzziness_values: Optional[List[float]] = None,
        num_permutations: int = 99,
    ) -> Dict[str, Any]:
        """POST /opgd/analyze → 202 {task_id, status, message, remaining_quota}。"""
        payload: Dict[str, Any] = {
            "upload_id": upload_id,
            "title": title,
            "analysis_model": analysis_model,
            "y_col": y_col,
            "x_cols": list(dict.fromkeys(x_cols)),
            "categorical_cols": list(dict.fromkeys(categorical_cols or [])),
            "methods": list(dict.fromkeys(methods or DEFAULT_METHODS)),
            "min_bins": min_bins,
            "max_bins": max_bins,
            "fuzziness_mode": fuzziness_mode,
            "fuzziness_values": fuzziness_values or [1.0, 2.0, 3.0, 4.0, 5.0],
            "num_permutations": num_permutations,
        }
        return self.request("POST", "/opgd/analyze", json=payload).json()

    def trial_analyze(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST /opgd/free-trial/analyze（试用通道请求体与服务端 schema 对齐，dict 透传）。"""
        return self.request("POST", "/opgd/free-trial/analyze", json=payload).json()

    # ------------------------------------------------------------------ 任务

    def list_tasks(self, task_type: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"limit": limit}
        if task_type:
            params["task_type"] = task_type
        return self.get_json("/tasks", params=params)

    def get_task(self, task_id: str) -> Dict[str, Any]:
        return self.get_json(f"/tasks/{task_id}")

    def cancel_task(self, task_id: str) -> Dict[str, Any]:
        return self.request("POST", f"/opgd/tasks/{task_id}/cancel").json()

    # ------------------------------------------------------------------ 报告与导出

    def get_report(self, task_id: str) -> Dict[str, Any]:
        return self.get_json(f"/opgd/tasks/{task_id}/report")

    def export_report(self, task_id: str) -> tuple[bytes, str]:
        """GET /opgd/tasks/{id}/export → (zip 字节, 建议文件名)。"""
        response = self.request("GET", f"/opgd/tasks/{task_id}/export")
        filename = _filename_from_disposition(response.headers.get("Content-Disposition", ""))
        return response.content, filename or f"opgd_report_{task_id}.zip"

    def export_chart(self, task_id: str, chart: str) -> bytes:
        """下载图表 PNG；chart ∈ {factor, interaction}。"""
        endpoint = CHART_ENDPOINTS.get(chart)
        if not endpoint:
            raise ValueError(f"未知图表类型：{chart}（可选 factor / interaction）")
        return self.request("GET", f"/opgd/tasks/{task_id}/charts/{endpoint}").content


def _filename_from_disposition(disposition: str) -> Optional[str]:
    """解析 Content-Disposition，优先取 RFC5987 编码的 filename*。"""
    if not disposition:
        return None
    target = None
    for part in disposition.split(";"):
        part = part.strip()
        if part.lower().startswith("filename*="):
            value = part.split("=", 1)[1].strip().strip('"')
            # 形如 UTF-8''%E6%8A%A5%E5%91%8A.zip
            if "''" in value:
                _, _, value = value.partition("''")
            from urllib.parse import unquote

            target = unquote(value)
            break
        if part.lower().startswith("filename="):
            target = part.split("=", 1)[1].strip().strip('"')
    return target


def dump_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)
