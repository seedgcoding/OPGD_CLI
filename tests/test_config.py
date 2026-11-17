"""config.py 行为测试：凭据保存合并、直连记忆保留。"""

from __future__ import annotations

from opgd_cli.config import clear_auth, get_profile, save_auth


def test_save_auth_merges_preserving_no_proxy(isolated_config):
    server = "https://opgd.example.com"
    # 模拟直连记忆先行写入
    profile = get_profile(server)
    from opgd_cli.config import load_config, save_config

    data = load_config()
    data.setdefault("profiles", {})[profile.name] = {
        "server": server,
        "no_proxy": True,
    }
    save_config(data)

    # 登录不应抹掉 no_proxy
    save_auth(server, "token-1", "bearer", "alice")
    merged = get_profile(server)
    assert merged.access_token == "token-1"
    assert merged.no_proxy is True
    assert merged.username == "alice"


def test_clear_auth_keeps_connection_memo(isolated_config):
    server = "https://opgd.example.com"
    save_auth(server, "token-1", "bearer", "alice")
    from opgd_cli.config import load_config, save_config

    data = load_config()
    data["profiles"][list(data["profiles"])[0]]["no_proxy"] = True
    save_config(data)

    removed = clear_auth(server)
    assert removed is True
    profile = get_profile(server)
    assert profile.access_token is None
    assert profile.no_proxy is True
    assert profile.server == server

    # 二次清除返回 False
    assert clear_auth(server) is False
