"""配置管理：~/.opgd/config.toml

结构::

    default_server = "https://opgd500.kkbvip.top"

    [profiles.server-name]
    server = "https://opgd500.kkbvip.top"
    access_token = "..."
    token_type = "bearer"
    username = "..."

命令行 ``--server`` > 环境变量 ``OPGD_SERVER`` > 配置文件 ``default_server`` > 内置默认值。
"""

from __future__ import annotations

import getpass
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - 3.10 分支
    import tomli as tomllib

try:
    import tomli_w
except ImportError:  # pragma: no cover
    tomli_w = None

from .exceptions import OPGDCLIError

DEFAULT_SERVER = "https://opgd500.kkbvip.top"
CONFIG_DIR = Path(os.environ.get("OPGD_CONFIG_DIR", Path.home() / ".opgd"))
CONFIG_FILE = CONFIG_DIR / "config.toml"


@dataclass
class Profile:
    """一个服务端连接配置（含可选的登录凭据）。"""

    name: str = "default"
    server: str = DEFAULT_SERVER
    access_token: Optional[str] = None
    token_type: str = "bearer"
    username: Optional[str] = None
    #: 直连记忆：True 表示曾确认系统代理对该服务端不可达，后续跳过代理
    no_proxy: bool = False

    @property
    def auth_header(self) -> Optional[dict]:
        if not self.access_token:
            return None
        scheme = self.token_type or "bearer"
        return {"Authorization": f"{scheme.capitalize()} {self.access_token}"}


def _ensure_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        try:
            os.chmod(CONFIG_DIR, stat.S_IRWXU)
        except OSError:
            pass


def load_config() -> dict:
    """读取配置文件，损坏时返回空字典（不抛异常，避免卡死 CLI）。"""
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, "rb") as fh:
            return tomllib.load(fh)
    except Exception:
        return {}


def save_config(data: dict) -> None:
    if tomli_w is None:  # pragma: no cover
        raise OPGDConfigError("缺少 tomli-w 依赖，无法写入配置")
    _ensure_dir()
    with open(CONFIG_FILE, "wb") as fh:
        tomli_w.dump(data, fh)
    if os.name == "posix":
        try:
            os.chmod(CONFIG_FILE, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


class OPGDConfigError(OPGDCLIError):
    """配置读写错误。"""


def _server_key(server: str) -> str:
    """把 server URL 归一化为 profile 键（去掉协议尾部斜杠差异没法完全一致，用原串小写）。"""
    return server.rstrip("/").lower().replace("://", "_")


def get_profile(server: Optional[str] = None) -> Profile:
    """解析当前生效的 Profile。

    优先级：显式 server 参数 > 环境变量 OPGD_SERVER > 配置文件 default_server > 默认值。
    """
    data = load_config()
    resolved = server or os.environ.get("OPGD_SERVER") or data.get("default_server") or DEFAULT_SERVER
    key = _server_key(resolved)
    profiles: dict = data.get("profiles") or {}
    stored = profiles.get(key) or {}
    return Profile(
        name=key,
        server=stored.get("server", resolved),
        access_token=stored.get("access_token"),
        token_type=stored.get("token_type", "bearer"),
        username=stored.get("username"),
        no_proxy=bool(stored.get("no_proxy", False)),
    )


def save_auth(server: str, access_token: str, token_type: str = "bearer", username: Optional[str] = None) -> None:
    """保存某个 server 的登录凭据（合并写入，保留 no_proxy 等已有记忆）。"""
    data = load_config()
    data.setdefault("profiles", {})
    key = _server_key(server)
    profile_data = {
        "server": server.rstrip("/"),
        "access_token": access_token,
        "token_type": token_type,
    }
    if username:
        profile_data["username"] = username
    existing: dict = data["profiles"].get(key) or {}
    existing.update(profile_data)
    data["profiles"][key] = existing
    data.setdefault("default_server", server.rstrip("/"))
    save_config(data)


def clear_auth(server: Optional[str] = None) -> bool:
    """清除凭据（保留 server 与 no_proxy 等连接记忆）；返回是否确实清除了凭据。"""
    profile = get_profile(server)
    data = load_config()
    profiles: dict = data.get("profiles") or {}
    entry: dict = profiles.get(profile.name) or {}
    if entry.get("access_token"):
        for field in ("access_token", "token_type", "username"):
            entry.pop(field, None)
        profiles[profile.name] = entry
        save_config(data)
        return True
    return False


def prompt_credentials() -> tuple[str, str]:
    """交互式获取账号密码（密码不回显）。"""
    try:
        username = input("账号: ").strip()
        password = getpass.getpass("密码: ")
    except (EOFError, KeyboardInterrupt):
        raise SystemExit(1)
    if not username or not password:
        raise OPGDCLIError("账号和密码不能为空")
    return username, password
