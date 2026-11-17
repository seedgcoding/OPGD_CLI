"""本地 OPGD 模拟服务 —— 不碰生产环境的全链路闭环测试。

复刻线上服务的关键行为契约（字段结构以 2026-11 线上抓包为准）：
- 登录签发 token（30 分钟语义由测试自行控制，这里不过期）
- 上传 → analyze 202 异步任务 → PENDING/PROCESSING → SUCCESS
- 一次性上传：任务终态后文件标记 CLEANED，复用 upload_id 会产出 FAILED 任务
- 额度扣减 / 额度不足 402 / 未登录或 token 错 401 / 可配置 429 限流
- 报告、导出 ZIP、图表 PNG

独立运行（手动体验）::

    python tests/mock_server.py --port 8092
    opgd --server http://127.0.0.1:8092 auth login ...
"""

from __future__ import annotations

import io
import json
import re
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

# 1x1 透明 PNG（魔数合法，足以让客户端校验通过）
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082"
)

TRIAL_REPORT = {
    "task_id": "trial-task-0001",
    "mode": "FREE_TRIAL",
    "title": "免费体验版因子探测结果 - mock.csv",
    "applied_config": {"methods": ["quantile"], "min_bins": 3, "max_bins": 7,
                       "y_col": "GDP", "x_cols": ["X1", "X2"], "categorical_cols": []},
    "dataset_summary": {"original_filename": "mock.csv", "effective_rows": 40,
                        "effective_columns": ["X1", "X2", "GDP"], "truncated": False},
    "factor_detector_q_values": [
        {"Factor": "X1", "q-statistic": 0.876},
        {"Factor": "X2", "q-statistic": 0.255},
    ],
    "masked_modules": {
        "interaction_detector": {"computed": True, "visible": False,
                                 "mask_title": "交互探测结果已生成",
                                 "mask_desc": "免费体验版仅保留遮挡预览"},
    },
}


def build_report(title: str = "OPGD 分析报告") -> Dict[str, Any]:
    """按线上真实结构构造完整报告（含按变量分组的 optimal_params）。"""
    return {
        "id": "mock-report",
        "title": title,
        "status": "SUCCESS",
        "summary": {"top_factor": "X1", "top_q_value": 0.8403, "significant_factor_count": 2},
        "runtime_ms": 534,
        "optimal_params": {
            "X1": {"method": "natural_breaks", "bins": 8, "q_value": 0.8403},
            "X2": {"method": "equal_interval", "bins": 5, "q_value": 0.1188},
        },
        "factor_detector": [
            {"Factor": "X1", "q-statistic": 0.8403, "p-value": 0.0},
            {"Factor": "X2", "q-statistic": 0.1188, "p-value": 0.12},
        ],
        "interaction_detector": {
            "factors": ["X1", "X2"],
            "matrix": [{"factor": "X1", "values": [None, 0.91]},
                       {"factor": "X2", "values": [None, None]}],
            "pairs": [{"Factor1": "X1", "Factor2": "X2", "q(X1)": 0.8403, "q(X2)": 0.1188,
                       "q(X1∩X2)": 0.9101, "Interaction": "Bi-enhance"}],
        },
        "risk_detector": {"X1": {"means": {"0": 1.0},
                                 "comparisons": [{"Stratum1": 0, "Stratum2": 1, "Mean1": 1.0,
                                                  "Mean2": 2.0, "t-statistic": -2.1,
                                                  "p-value": 0.04, "Significant": True}]}},
        "ecological_detector": [{"Factor1": "X1", "Factor2": "X2", "SSW1": 10.0,
                                 "SSW2": 20.0, "Significant": "Yes"}],
    }


def build_export_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("因子探测结果.csv", "Factor,q-statistic,p-value\nX1,0.8403,0\n")
        zf.writestr("结果摘要.csv", "key,value\nrow_count,40\n")
    return buf.getvalue()


class MockState:
    """内存态：用户 / 上传 / 任务。"""

    def __init__(self, tokens: int = 3, rate_limit_after: int = 0):
        self.users: Dict[str, Dict[str, Any]] = {
            "tester": {"password": "right-pass", "token": f"mock-token-{uuid.uuid4().hex[:8]}",
                       "ai_tokens": tokens, "consumed": 0},
            "poor": {"password": "poor-pass", "token": f"mock-token-{uuid.uuid4().hex[:8]}",
                     "ai_tokens": 0, "consumed": 0},
        }
        self.uploads: Dict[int, Dict[str, Any]] = {}
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.trial_uploads: Dict[str, Dict[str, Any]] = {}
        self.upload_seq = 100
        self.rate_limit_after = rate_limit_after  # >0 时：上传次数超过该值即 429
        self.upload_count = 0
        self._lock = threading.Lock()

    def user_by_token(self, auth_header: Optional[str]) -> Optional[Dict[str, Any]]:
        if not auth_header:
            return None
        m = re.match(r"Bearer\s+(.+)", auth_header)
        if not m:
            return None
        for u in self.users.values():
            if u["token"] == m.group(1):
                return u
        return None


def parse_multipart(body: bytes, content_type: str) -> Optional[Dict[str, Any]]:
    """极简 multipart 解析：取第一个带 filename 的文件字段。"""
    m = re.search(r"boundary=([^;]+)", content_type)
    if not m:
        return None
    boundary = m.group(1).strip().encode()
    for part in body.split(b"--" + boundary):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        header_blob, _, payload = part.partition(b"\r\n\r\n")
        headers = header_blob.decode("utf-8", "replace")
        fn = re.search(r'filename="([^"]*)"', headers)
        if fn:
            return {"filename": fn.group(1), "content": payload}
    return None


class MockHandler(BaseHTTPRequestHandler):
    state: MockState  # 由 server 子类注入
    protocol_version = "HTTP/1.1"  # keep-alive：与 httpx 连接池配合，避免复用已被关闭的连接

    # ------------------------------------------------------------- 基础设施

    def log_message(self, *args):  # 静默
        pass

    def _send(self, status: int, payload: Any = None, raw: Optional[bytes] = None,
              content_type: str = "application/json", headers: Optional[dict] = None):
        body = raw if raw is not None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        """完整读取请求体（必须读掉，否则 keep-alive 下残留字节会破坏下一个请求）。

        注意：keep-alive 时同一 handler 实例处理多个请求，body 绝不能缓存在 self 上。
        """
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _json(self, body: bytes) -> Dict[str, Any]:
        try:
            return json.loads(body or b"{}")
        except Exception:
            return {}

    def _auth_user(self):
        user = self.state.user_by_token(self.headers.get("Authorization"))
        if not user:
            self._send(401, {"detail": "Could not validate credentials"})
        return user

    # ------------------------------------------------------------- 路由

    def do_GET(self):
        st = self.state
        path = self.path.split("?")[0]
        if path == "/api/v1/health":
            return self._send(200, {"success": True, "data": {"status": "healthy",
                                                              "service": "OPGD Mock", "version": "0.0.0-mock"}})
        user = self._auth_user()
        if not user:
            return
        if path == "/api/v1/auth/me":
            return self._send(200, {"username": self._username(user), "role": "USER", "ai_tokens": user["ai_tokens"]})
        if path == "/api/v1/profile/":
            return self._send(200, {"username": self._username(user), "role_label": "普通用户",
                                    "remaining_quota": user["ai_tokens"], "consumed_count": user["consumed"],
                                    "account_status_label": "正常", "created_at": "2026-01-01T00:00:00"})
        m = re.match(r"^/api/v1/tasks$", path)
        if m:
            items = [self._serialize_task(t) for t in st.tasks.values() if t["user"] is user]
            items.sort(key=lambda t: t["created_at"], reverse=True)
            return self._send(200, items[:50])
        m = re.match(r"^/api/v1/tasks/([^/]+)$", path)
        if m:
            task = st.tasks.get(m.group(1))
            if not task or task["user"] is not user:
                return self._send(404, {"detail": "任务不存在或无权限访问"})
            return self._send(200, self._serialize_task(task))
        m = re.match(r"^/api/v1/opgd/tasks/([^/]+)/report$", path)
        if m:
            task = st.tasks.get(m.group(1))
            if not task or task["user"] is not user:
                return self._send(404, {"detail": "任务不存在"})
            if task["status"] != "SUCCESS":
                return self._send(400, {"detail": "任务未完成"})
            return self._send(200, build_report(title=task["title"]))
        m = re.match(r"^/api/v1/opgd/tasks/([^/]+)/export$", path)
        if m:
            task = st.tasks.get(m.group(1))
            if not task or task["user"] is not user or task["status"] != "SUCCESS":
                return self._send(404, {"detail": "任务不存在"})
            zip_name = f"OPGD分析报告_{task['task_id']}.zip"
            quoted = zip_name.encode("utf-8").decode("latin-1")
            return self._send(200, raw=build_export_zip(), content_type="application/zip",
                              headers={"Content-Disposition": f'attachment; filename="report.zip"; filename*=UTF-8\'\'{quoted}'})
        m = re.match(r"^/api/v1/opgd/tasks/([^/]+)/charts/(factor|interaction)-detector\.png$", path)
        if m:
            return self._send(200, raw=TINY_PNG, content_type="image/png")
        m = re.match(r"^/api/v1/opgd/uploads/(\d+)$", path)
        if m:
            up = st.uploads.get(int(m.group(1)))
            if not up or up["user"] is not user:
                return self._send(404, {"detail": "上传文件不存在或无权限访问"})
            return self._send(200, self._upload_json(up))
        return self._send(404, {"detail": "Not Found"})

    def do_POST(self):
        st = self.state
        path = self.path.split("?")[0]
        body = self._read_body()  # 每个请求独立读取，保证 keep-alive 连接干净
        if path == "/api/v1/auth/login":
            payload = self._json(body)
            for name, u in st.users.items():
                if name == payload.get("phone") and u["password"] == payload.get("password"):
                    return self._send(200, {"access_token": u["token"], "token_type": "bearer"})
            return self._send(401, {"detail": "账号或密码错误"})
        if path == "/api/v1/opgd/free-trial/uploads":
            st.upload_count += 1
            if st.rate_limit_after and st.upload_count > st.rate_limit_after:
                return self._send(429, {"detail": "请求过于频繁"}, headers={"Retry-After": "3"})
            file = parse_multipart(body, self.headers.get("Content-Type", ""))
            token = uuid.uuid4().hex
            st.trial_uploads[token] = {"filename": file["filename"] if file else "x.csv"}
            return self._send(200, {"upload_token": token, "original_filename": file["filename"] if file else "x.csv",
                                    "effective_rows": 40, "effective_columns": ["X1", "X2", "GDP"],
                                    "columns": [
                                        {"name": "X1", "dtype": "float64", "inferred_role": "numeric",
                                         "missing_count": 0, "missing_ratio": 0.0, "unique_count": 40,
                                         "sample_values": [1.0], "is_recommended_y": True, "is_recommended_x": True},
                                        {"name": "X2", "dtype": "float64", "inferred_role": "numeric",
                                         "missing_count": 0, "missing_ratio": 0.0, "unique_count": 40,
                                         "sample_values": [2.0], "is_recommended_y": False, "is_recommended_x": True},
                                        {"name": "GDP", "dtype": "float64", "inferred_role": "numeric",
                                         "missing_count": 0, "missing_ratio": 0.0, "unique_count": 40,
                                         "sample_values": [3.0], "is_recommended_y": True, "is_recommended_x": True},
                                    ]})
        if path == "/api/v1/opgd/free-trial/analyze":
            payload = self._json(body)
            if payload.get("upload_token") not in st.trial_uploads:
                return self._send(400, {"detail": "上传凭证无效或已过期"})
            report = json.loads(json.dumps(TRIAL_REPORT, ensure_ascii=False))
            report["applied_config"]["y_col"] = payload.get("y_col", "GDP")
            report["applied_config"]["x_cols"] = payload.get("x_cols", [])
            report["applied_config"]["categorical_cols"] = payload.get("categorical_cols", [])
            return self._send(200, report)

        user = self._auth_user()
        if not user:
            return

        if path == "/api/v1/opgd/uploads":
            st.upload_count += 1
            if st.rate_limit_after and st.upload_count > st.rate_limit_after:
                return self._send(429, {"detail": "请求过于频繁"}, headers={"Retry-After": "3"})
            file = parse_multipart(body, self.headers.get("Content-Type", ""))
            st.upload_seq += 1
            upload_id = st.upload_seq
            st.uploads[upload_id] = {
                "id": upload_id, "user": user, "status": "READY",
                "original_filename": file["filename"] if file else "x.csv",
                "columns": [
                    {"name": "X1", "dtype": "float64", "inferred_role": "numeric", "missing_count": 0,
                     "missing_ratio": 0.0, "unique_count": 40, "sample_values": [1.0],
                     "is_recommended_y": True, "is_recommended_x": True},
                    {"name": "X2", "dtype": "float64", "inferred_role": "numeric", "missing_count": 0,
                     "missing_ratio": 0.0, "unique_count": 40, "sample_values": [2.0],
                     "is_recommended_y": False, "is_recommended_x": True},
                    {"name": "GDP", "dtype": "float64", "inferred_role": "numeric", "missing_count": 0,
                     "missing_ratio": 0.0, "unique_count": 40, "sample_values": [3.0],
                     "is_recommended_y": True, "is_recommended_x": True},
                ],
            }
            return self._send(200, self._upload_json(st.uploads[upload_id]))

        if path == "/api/v1/opgd/analyze":
            payload = self._json(body)
            upload = st.uploads.get(payload.get("upload_id"))
            if not upload or upload["user"] is not user:
                return self._send(404, {"detail": "上传文件不存在或无权限访问"})
            if user["ai_tokens"] <= 0:
                return self._send(402, {"detail": "剩余次数不足，请充值或联系管理员"})
            user["ai_tokens"] -= 1
            user["consumed"] += 1
            task_id = str(uuid.uuid4())
            task = {
                "task_id": task_id, "task_type": "opgd_analysis", "user": user,
                "status": "PENDING", "upload": upload,
                "title": payload.get("title") or "未命名分析",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "input_summary": {"title": payload.get("title"), "upload_id": payload.get("upload_id"),
                                  "analysis_model": payload.get("analysis_model", "opgd"),
                                  "y_col": payload.get("y_col"), "x_cols": payload.get("x_cols", []),
                                  "categorical_cols": payload.get("categorical_cols", [])},
                "error": "",
            }
            st.tasks[task_id] = task
            # 模拟异步生命周期；上传是一次性的：任务终态后文件 CLEANED
            if upload["status"] != "READY":
                threading.Timer(0.2, lambda: self._fail_task(task_id)).start()
            else:
                threading.Timer(0.3, lambda: self._advance(task_id)).start()
            return self._send(202, {"task_id": task_id, "status": "PENDING", "message": "已受理",
                                    "remaining_quota": user["ai_tokens"]})

        m = re.match(r"^/api/v1/opgd/tasks/([^/]+)/cancel$", path)
        if m:
            task = st.tasks.get(m.group(1))
            if not task or task["user"] is not user:
                return self._send(404, {"detail": "任务不存在"})
            if task["status"] in ("PENDING", "PROCESSING"):
                task["status"] = "CANCELLED"
            return self._send(200, {"ok": True})
        return self._send(404, {"detail": "Not Found"})

    # ------------------------------------------------------------- 辅助

    def _username(self, user: Dict[str, Any]) -> str:
        return next(k for k, v in self.state.users.items() if v is user)

    def _upload_json(self, up: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": up["id"], "original_filename": up["original_filename"], "file_type": "csv",
                "file_size": 833, "row_count": 40, "column_count": 3,
                "columns": up["columns"], "preview_rows": [], "created_at": "2026-01-01T00:00:00"}

    def _serialize_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        out = {"task_id": task["task_id"], "task_type": "opgd_analysis", "status": task["status"],
               "created_at": task["created_at"], "cancelable": task["status"] in ("PENDING", "PROCESSING"),
               "input_summary": task["input_summary"]}
        if task["status"] in ("FAILED", "CANCELLED") and task.get("error"):
            out["error"] = task["error"]
        if task["status"] == "SUCCESS":
            out["result"] = {"report_available": True}
        return out

    def _advance(self, task_id: str):
        task = self.state.tasks.get(task_id)
        if not task or task["status"] != "PENDING":
            return
        task["status"] = "PROCESSING"
        threading.Timer(0.4, lambda: self._succeed(task_id)).start()

    def _succeed(self, task_id: str):
        task = self.state.tasks.get(task_id)
        if not task or task["status"] != "PROCESSING":
            return
        task["status"] = "SUCCESS"
        task["upload"]["status"] = "CLEANED"  # 一次性上传语义

    def _fail_task(self, task_id: str):
        task = self.state.tasks.get(task_id)
        if not task:
            return
        task["status"] = "FAILED"
        task["error"] = "[Errno 2] No such file or directory: '/mock/storage/opgd/uploads/gone.csv'"


class MockOPGDServer(ThreadingHTTPServer):
    def __init__(self, state: Optional[MockState] = None, port: int = 0):
        self.state = state or MockState()
        handler = type("BoundHandler", (MockHandler,), {"state": self.state})
        super().__init__(("127.0.0.1", port), handler)

    @property
    def base_url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"


def main():  # pragma: no cover - 手动体验入口
    import argparse

    parser = argparse.ArgumentParser(description="本地 OPGD 模拟服务")
    parser.add_argument("--port", type=int, default=8092)
    parser.add_argument("--tokens", type=int, default=3, help="tester 账号的初始分析次数")
    parser.add_argument("--rate-limit-after", type=int, default=0, help="上传次数超过该值后返回 429（0=关闭）")
    args = parser.parse_args()

    server = MockOPGDServer(MockState(tokens=args.tokens, rate_limit_after=args.rate_limit_after),
                            port=args.port)
    tester = server.state.users["tester"]
    print(f"Mock OPGD API: {server.base_url}")
    print(f"登录账号: tester / {tester['password']}  （剩余 {tester['ai_tokens']} 次）")
    print("Ctrl+C 退出")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
