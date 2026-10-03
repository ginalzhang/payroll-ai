"""Quick sanity tests for detectors.py — not exhaustive, just smoke."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from detectors import (
    cohort_stats,
    detect_compression,
    detect_mismatch,
    detect_overpayment,
    detect_underpayment,
    load_employees,
    run_all,
    total_exposure,
)
from schema import (
    COL_ANNUAL_SALARY,
    COL_COHORT,
    COL_ID,
    COL_NAME,
    MIN_COHORT_SIZE,
    RULE_COMPRESSION,
    RULE_MISMATCH,
    RULE_OVERPAY,
    RULE_UNDERPAY,
)


def test_load_employees_adds_derived_columns():
    df = load_employees()
    assert len(df) == 1470
    for col in (COL_ANNUAL_SALARY, COL_NAME, COL_COHORT):
        assert col in df.columns, f"missing {col}"
    assert (df[COL_ANNUAL_SALARY] > 0).all()
    assert df[COL_NAME].str.contains(" ").all()
    assert df[COL_COHORT].str.contains(" L").all()


def test_cohort_stats_filters_small_cohorts():
    df = load_employees()
    stats = cohort_stats(df)
    assert (stats["size"] >= MIN_COHORT_SIZE).all()
    assert set(["median", "Q1", "Q3", "IQR", "lower_fence", "upper_fence", "size"]).issubset(stats.columns)
    assert (stats["Q3"] >= stats["Q1"]).all()


def test_each_rule_returns_a_list():
    df = load_employees()
    stats = cohort_stats(df)
    assert isinstance(detect_underpayment(df, stats), list)
    assert isinstance(detect_overpayment(df, stats), list)
    assert isinstance(detect_compression(df, stats), list)
    assert isinstance(detect_mismatch(df), list)


def test_run_all_shape_and_columns():
    df = load_employees()
    out = run_all(df)
    assert isinstance(out, pd.DataFrame)
    expected = {
        "employee_id", "name", "role", "level", "department",
        "annual_salary", "rule", "severity", "reason", "evidence",
    }
    assert expected.issubset(set(out.columns))
    assert len(out) > 0
    assert set(out["rule"].unique()).issubset({
        RULE_UNDERPAY, RULE_OVERPAY, RULE_COMPRESSION, RULE_MISMATCH,
    })
    assert out["evidence"].apply(lambda e: isinstance(e, dict)).all()


def test_total_exposure_is_positive_int():
    df = load_employees()
    stats = cohort_stats(df)
    out = run_all(df)
    exposure = total_exposure(out, stats)
    assert isinstance(exposure, int)
    assert exposure > 0


if __name__ == "__main__":
    test_load_employees_adds_derived_columns()
    test_cohort_stats_filters_small_cohorts()
    test_each_rule_returns_a_list()
    test_run_all_shape_and_columns()
    test_total_exposure_is_positive_int()
    print("All sanity tests passed.")
