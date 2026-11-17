"""utils.py 参数解析测试。"""

from __future__ import annotations

import pytest

from opgd_cli.exceptions import OPGDCLIError
from opgd_cli.utils import parse_bins, parse_floats, parse_methods, validate_upload_file


def test_parse_bins_variants():
    assert parse_bins("3:8") == (3, 8)
    assert parse_bins("3-8") == (3, 8)
    assert parse_bins("5") == (5, 5)
    assert parse_bins(None) == (3, 8)


def test_parse_bins_invalid():
    with pytest.raises(OPGDCLIError):
        parse_bins("8:3")  # min > max
    with pytest.raises(OPGDCLIError):
        parse_bins("1:8")  # min < 2
    with pytest.raises(OPGDCLIError):
        parse_bins("3:21")  # max > 20
    with pytest.raises(OPGDCLIError):
        parse_bins("abc")


def test_parse_methods_default_and_custom():
    assert parse_methods(None, "opgd") == ["equal_interval", "quantile", "natural_breaks", "geometric"]
    assert parse_methods("quantile,natural_breaks", "opgd") == ["quantile", "natural_breaks"]
    # 重复去重
    assert parse_methods("quantile,quantile", "opgd") == ["quantile"]


def test_parse_methods_fuzzygd_exclusive():
    assert "kmeans" in parse_methods("kmeans", "fuzzygd")
    with pytest.raises(OPGDCLIError):
        parse_methods("kmeans", "opgd")  # opgd 不支持 kmeans


def test_parse_floats():
    assert parse_floats("1,2,3") == [1.0, 2.0, 3.0]
    assert parse_floats(None) is None
    with pytest.raises(OPGDCLIError):
        parse_floats("1,0,-2")  # 非正数
    with pytest.raises(OPGDCLIError):
        parse_floats("a,b")


def test_validate_upload_file(sample_csv):
    path = validate_upload_file(sample_csv)
    assert path == sample_csv


def test_validate_upload_file_rejects_suffix(tmp_path):
    bad = tmp_path / "data.txt"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(OPGDCLIError):
        validate_upload_file(bad)
    with pytest.raises(OPGDCLIError):
        validate_upload_file(tmp_path / "missing.csv")
