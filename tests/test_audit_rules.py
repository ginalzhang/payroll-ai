"""Tests for audit_rules: cohort exclusion, data-quality edge cases, one row per employee."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from audit_rules import run_audit, summary, validate  # noqa: E402
from schema import DATA_PATH  # noqa: E402

BASE = {"JobRole": "Analyst", "JobLevel": 2, "Department": "Sales", "MonthlyIncome": 5000,
        "YearsAtCompany": 3, "YearsSinceLastPromotion": 2, "PercentSalaryHike": 12}


def make(rows: list[dict], start_id: int = 1) -> pd.DataFrame:
    return pd.DataFrame([{**BASE, "EmployeeNumber": start_id + i, **r} for i, r in enumerate(rows)])


def emp(res, eid: int) -> pd.Series:
    return res.employees.set_index("EmployeeNumber").loc[eid]


def test_cohort_under_five_is_excluded():
    # Four people, one paid far below the others: would be flagged if the cohort counted.
    df = make([{}, {}, {}, {"MonthlyIncome": 2000}])
    res = run_audit(df)
    assert res.excluded_small_cohort == 4
    assert not res.employees["evaluated"].any()
    assert res.flags.empty
    assert summary(res)["cohorts"] == 0


def test_cohort_of_five_is_evaluated():
    df = make([{}, {}, {}, {}, {"MonthlyIncome": 2000}])
    res = run_audit(df)
    assert res.excluded_small_cohort == 0
    assert list(res.flags["rule"]) == ["under"]
    assert res.flags.iloc[0]["severity"] == "High"


def test_cohort_includes_department():
    # Same role and level split across two departments: two cohorts of 3, both too small.
    df = make([{}, {}, {}, {"Department": "HR"}, {"Department": "HR"}, {"Department": "HR"}])
    res = run_audit(df)
    assert res.excluded_small_cohort == 6


@pytest.mark.parametrize("bad", [None, 0, -100])
def test_missing_or_zero_salary_is_skipped(bad):
    df = make([{}] * 5 + [{"MonthlyIncome": bad}])
    res = run_audit(df)
    row = emp(res, 6)
    assert res.skipped_missing_salary == 1
    assert row["missing_salary"] and not row["evaluated"]
    assert pd.isna(row["AnnualSalary"])
    assert res.flags.empty
    # The skipped row must not drag the cohort median or count toward n.
    assert emp(res, 1)["n"] == 5


def test_non_numeric_values_are_coerced_and_skipped():
    df = make([{}] * 5 + [{"YearsAtCompany": "ten"}])
    res = run_audit(df)
    assert res.coerced_values["YearsAtCompany"] == 1
    assert res.skipped_invalid == 1
    assert not emp(res, 6)["evaluated"]
    assert validate(df).checks[5]["status"] == "warning"


def test_duplicate_employee_number_keeps_first():
    df = make([{}] * 5 + [{"MonthlyIncome": 2000}])
    dup = df.iloc[[5]].assign(MonthlyIncome=9999)
    res = run_audit(pd.concat([df, dup]))
    assert res.duplicate_ids == 1
    assert res.total_rows == 7
    assert len(res.employees) == 6
    assert emp(res, 6)["AnnualSalary"] == 2000 * 12


def test_multiple_flags_produce_one_employee_row():
    # Underpaid (ratio < 0.82) AND promoted this year with a 2% raise at level 2.
    df = make([{}] * 5 + [{"MonthlyIncome": 3000, "YearsSinceLastPromotion": 0, "PercentSalaryHike": 2}])
    res = run_audit(df)
    assert sorted(res.flags.loc[res.flags["EmployeeNumber"] == 6, "rule"]) == ["promo", "under"]
    flagged = res.employees[res.employees["flag_count"] > 0]
    assert flagged["EmployeeNumber"].tolist() == [6]
    row = emp(res, 6)
    assert row["flag_count"] == 2
    assert row["top_severity"] == "High"
    median = 5000 * 12
    promo = round(3000 * 12 * (8 - 2) / 100)
    assert row["exposure"] == pytest.approx((median - 3000 * 12) + promo)
    assert summary(res)["flagged"] == 1


def test_top_severity_is_highest_of_flags():
    # Medium underpayment (0.82 <= ratio < 0.88) plus a High promo flag.
    df = make([{}] * 5 + [{"MonthlyIncome": 4250, "YearsSinceLastPromotion": 0, "PercentSalaryHike": 1}])
    res = run_audit(df)
    sev = dict(zip(res.flags["rule"], res.flags["severity"]))
    assert sev == {"under": "Medium", "promo": "High"}
    assert emp(res, 6)["top_severity"] == "High"


def test_overpayment_not_counted_in_exposure():
    df = make([{}] * 5 + [{"MonthlyIncome": 9000}])
    res = run_audit(df)
    s = summary(res)
    assert list(res.flags["rule"]) == ["over"]
    assert res.flags.iloc[0]["severity"] == "Low"
    assert s["exposure"] == 0
    assert s["exposure_people"] == 0
    p75 = res.employees["p75"].iloc[0]
    assert s["above_band_total"] == pytest.approx(9000 * 12 - p75)
    assert s["above_band_people"] == 1


def test_compression_requires_tenure():
    df = make([{}] * 5 + [{"MonthlyIncome": 4700, "YearsAtCompany": 12}, {"MonthlyIncome": 4700}])
    res = run_audit(df)
    assert res.flags["EmployeeNumber"].tolist() == [6]
    assert res.flags.iloc[0]["rule"] == "comp"


def test_zero_flag_dataset():
    df = make([{}] * 8)
    res = run_audit(df)
    s = summary(res)
    assert res.flags.empty
    assert s["flagged"] == 0 and s["exposure"] == 0 and s["high_flags"] == 0
    assert s["above_band_total"] == 0
    assert (res.employees["flag_count"] == 0).all()
    assert s["evaluated"] == 8


def test_validate_reports_renamed_and_missing_columns():
    df = make([{}]).rename(columns={"MonthlyIncome": "Monthly Income"}).drop(columns=["PercentSalaryHike"])
    v = validate(df)
    checks = {c["col"]: c for c in v.checks}
    assert not v.ok
    assert checks["MonthlyIncome"]["status"] == "missing"
    assert "Monthly Income" in checks["MonthlyIncome"]["note"]
    assert checks["PercentSalaryHike"]["note"] == "Missing"
    assert checks["JobRole"]["status"] == "found"


def test_bundled_dataset_smoke():
    df = pd.read_csv(DATA_PATH)
    assert validate(df).ok
    res = run_audit(df)
    s = summary(res)
    assert s["total"] == 1470
    assert res.employees["EmployeeNumber"].is_unique
    assert s["evaluated"] + res.excluded_small_cohort + res.skipped_missing_salary + res.skipped_invalid == 1470
    assert s["exposure"] > 0 and s["above_band_total"] > 0
