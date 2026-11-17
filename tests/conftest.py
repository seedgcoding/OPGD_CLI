"""测试公共夹具：respx 模拟 + CLI Runner + 示例数据。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from opgd_cli.config import CONFIG_FILE

runner = CliRunner()

SAMPLE_UPLOAD = {
    "upload_token": "tok-123",
    "original_filename": "sample.csv",
    "accepted_file_size": 833,
    "effective_rows": 40,
    "effective_columns": ["X1", "X2", "GDP"],
    "columns": [
        {"name": "X1", "dtype": "float64", "inferred_role": "numeric", "missing_count": 0,
         "missing_ratio": 0.0, "unique_count": 40, "sample_values": [1.0], "is_recommended_y": True,
         "is_recommended_x": True},
        {"name": "X2", "dtype": "float64", "inferred_role": "numeric", "missing_count": 0,
         "missing_ratio": 0.0, "unique_count": 40, "sample_values": [2.0], "is_recommended_y": False,
         "is_recommended_x": True},
        {"name": "GDP", "dtype": "float64", "inferred_role": "numeric", "missing_count": 0,
         "missing_ratio": 0.0, "unique_count": 40, "sample_values": [3.0], "is_recommended_y": True,
         "is_recommended_x": True},
    ],
}

SAMPLE_TRIAL_REPORT = {
    "task_id": "task-trial-1",
    "mode": "FREE_TRIAL",
    "title": "免费体验版因子探测结果 - sample.csv",
    "applied_config": {"methods": ["quantile"], "min_bins": 3, "max_bins": 7, "y_col": "GDP",
                       "x_cols": ["X1", "X2"], "categorical_cols": []},
    "dataset_summary": {"original_filename": "sample.csv", "effective_rows": 40,
                        "effective_columns": ["X1", "X2", "GDP"], "truncated": False},
    "factor_detector_q_values": [
        {"Factor": "X1", "q-statistic": 0.8762},
        {"Factor": "X2", "q-statistic": 0.2549},
    ],
    "factor_chart_spec": {"title": "因子探测器 q 值"},
    "masked_modules": {
        "interaction_detector": {"computed": True, "visible": False,
                                 "mask_title": "交互探测结果已生成", "mask_desc": "免费体验版仅保留遮挡预览"},
    },
}

SAMPLE_TASK_PENDING = {
    "task_id": "task-1",
    "task_type": "opgd_analysis",
    "status": "PENDING",
    "created_at": "2026-11-12T10:00:00",
    "cancelable": True,
    "input_summary": {"title": "t", "upload_id": 1, "analysis_model": "opgd", "y_col": "GDP",
                      "x_cols": ["X1"], "categorical_cols": [], "methods": ["quantile"],
                      "min_bins": 3, "max_bins": 8, "fuzziness_values": [], "num_permutations": 99},
}

SAMPLE_TASK_SUCCESS = {**SAMPLE_TASK_PENDING, "status": "SUCCESS", "result": {"report_available": True}}

SAMPLE_FULL_REPORT = {
    "id": "task-1",
    "title": "OPGD 分析报告",
    "status": "SUCCESS",
    "summary": {"top_factor": "X1", "top_q_value": 0.88, "significant_factor_count": 1},
    "runtime_ms": 1234,
    "optimal_params": {"method": "quantile", "bins": 5},
    "factor_detector": [{"Factor": "X1", "q-statistic": 0.88, "p-value": 0.01}],
    "interaction_detector": {
        "factors": ["X1", "X2"],
        "matrix": [{"factor": "X1", "values": [None, 0.9]}, {"factor": "X2", "values": [None, None]}],
        "pairs": [{"Factor1": "X1", "Factor2": "X2", "q(X1)": 0.88, "q(X2)": 0.25,
                   "q(X1∩X2)": 0.91, "Interaction": "nonlinearity_enhanced"}],
    },
    "risk_detector": {"X1": {"means": {"1": 1.0},
                             "comparisons": [{"Stratum1": 1, "Stratum2": 2, "Mean1": 1.0, "Mean2": 2.0,
                                              "t-statistic": -2.1, "p-value": 0.04, "Significant": True}]}},
    "ecological_detector": [{"Factor1": "X1", "Factor2": "X2", "SSW1": 10.0, "SSW2": 20.0,
                             "Significant": "Yes"}],
}


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """把配置文件指到临时目录，避免污染用户 ~/.opgd。"""
    config_dir = tmp_path / ".opgd"
    monkeypatch.setattr("opgd_cli.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("opgd_cli.config.CONFIG_FILE", config_dir / "config.toml")
    return config_dir


@pytest.fixture
def sample_csv(tmp_path) -> Path:
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(
        "X1,X2,GDP\n" + "\n".join(f"{i}.5,{i}.2,{i}.9" for i in range(10)),
        encoding="utf-8",
    )
    return csv_path


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
