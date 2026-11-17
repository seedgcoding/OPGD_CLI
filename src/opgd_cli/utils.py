"""命令行参数解析辅助。"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from .exceptions import OPGDCLIError

ALLOWED_UPLOAD_SUFFIXES = {".csv", ".xlsx", ".xls"}
ALLOWED_METHODS_OPGD = {"equal_interval", "quantile", "natural_breaks", "geometric", "std_mean"}
ALLOWED_METHODS_FUZZYGD = ALLOWED_METHODS_OPGD | {"kmeans", "rgd"}

METHOD_LABELS = {
    "equal_interval": "等间距",
    "quantile": "分位数",
    "natural_breaks": "自然断点",
    "geometric": "几何间隔",
    "std_mean": "均值标准差",
    "kmeans": "K-Means",
    "rgd": "RGD",
}


def parse_bins(spec: Optional[str]) -> Tuple[int, int]:
    """把 "3:8" / "3-8" / "5" 解析为 (min_bins, max_bins)。"""
    if not spec:
        return 3, 8
    text = spec.replace("：", ":").replace("～", ":").replace("~", ":").replace("-", ":").strip()
    if ":" in text:
        left, _, right = text.partition(":")
        try:
            min_bins, max_bins = int(left), int(right)
        except ValueError:
            raise OPGDCLIError(f"分级数格式无法解析：{spec!r}，示例：--bins 3:8")
    else:
        try:
            min_bins = max_bins = int(text)
        except ValueError:
            raise OPGDCLIError(f"分级数格式无法解析：{spec!r}，示例：--bins 3:8")
    if not (2 <= min_bins <= max_bins <= 20):
        raise OPGDCLIError("分级数需满足 2 <= 最小分级数 <= 最大分级数 <= 20")
    return min_bins, max_bins


def parse_methods(spec: Optional[str], model: str) -> List[str]:
    """把 "quantile,natural_breaks" 解析为列表并校验。"""
    allowed = ALLOWED_METHODS_FUZZYGD if model == "fuzzygd" else ALLOWED_METHODS_OPGD
    if not spec:
        base = ["equal_interval", "quantile", "natural_breaks", "geometric"]
        return [m for m in base if m in allowed]
    methods = [m.strip() for m in spec.replace("，", ",").split(",") if m.strip()]
    invalid = [m for m in methods if m not in allowed]
    if invalid:
        raise OPGDCLIError(
            f"不支持的离散化方法：{', '.join(invalid)}（{model} 模型可选：{', '.join(sorted(allowed))}）"
        )
    return list(dict.fromkeys(methods))


def parse_floats(spec: Optional[str]) -> Optional[List[float]]:
    """把 "1,2,3" 解析为浮点列表（模糊系数）。"""
    if not spec:
        return None
    try:
        values = [float(v) for v in spec.replace("，", ",").split(",") if v.strip()]
    except ValueError:
        raise OPGDCLIError(f"模糊系数格式无法解析：{spec!r}，示例：--fz-values 1,2,3")
    if any(v <= 0 for v in values):
        raise OPGDCLIError("模糊系数必须为正数")
    return values


def validate_upload_file(path: Path) -> Path:
    """校验待上传文件存在且后缀合法。"""
    path = Path(path)
    if not path.is_file():
        raise OPGDCLIError(f"文件不存在：{path}")
    if path.suffix.lower() not in ALLOWED_UPLOAD_SUFFIXES:
        raise OPGDCLIError(
            f"不支持的文件类型 {path.suffix!r}（支持：{', '.join(sorted(ALLOWED_UPLOAD_SUFFIXES))}）"
        )
    if path.stat().st_size > 50 * 1024 * 1024:
        raise OPGDCLIError("文件超过 50MB 平台上限")
    return path


def format_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{num_bytes}B"  # pragma: no cover
