"""PayGuard audit rules. Pure pandas, no Streamlit imports."""
from __future__ import annotations
from dataclasses import dataclass, field
import pandas as pd

REQUIRED_COLUMNS = [
    "EmployeeNumber", "JobRole", "JobLevel", "Department", "MonthlyIncome",
    "YearsAtCompany", "YearsSinceLastPromotion", "PercentSalaryHike",
]
NUMERIC_COLUMNS = ["EmployeeNumber", "JobLevel", "MonthlyIncome", "YearsAtCompany",
                   "YearsSinceLastPromotion", "PercentSalaryHike"]


@dataclass
class Thresholds:
    min_cohort: int = 5
    under_high: float = 0.82
    under_med: float = 0.88
    over_low: float = 1.28
    promo_min_raise: float = 4.0
    promo_expected_raise: float = 8.0
    compression_tenure: int = 10
    compression_ratio: float = 0.97


RULE_NAMES = {
    "under": "Underpayment",
    "promo": "Promotion without raise",
    "comp": "Salary compression",
    "over": "Above band",
}
SEV_RANK = {"High": 3, "Medium": 2, "Low": 1}


@dataclass
class ValidationResult:
    ok: bool
    checks: list[dict] = field(default_factory=list)  # {col, status: found|missing|warning, note}


@dataclass
class AuditResult:
    employees: pd.DataFrame          # one row per employee, all columns + audit fields
    flags: pd.DataFrame              # one row per flag (EmployeeNumber, rule, severity, impact, reason)
    cohorts: pd.DataFrame            # cohort stats
    skipped_missing_salary: int
    excluded_small_cohort: int
    duplicate_ids: int
    coerced_values: dict[str, int]
    skipped_invalid: int = 0         # rows with a blank/non-numeric required value (incl. missing ID)
    total_rows: int = 0              # rows in the input file, before any dropping


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def validate(df: pd.DataFrame) -> ValidationResult:
    checks, ok = [], True
    by_norm = {_norm(c): c for c in df.columns}
    for col in REQUIRED_COLUMNS:
        if col in df.columns:
            note = ""
            if col in NUMERIC_COLUMNS:
                bad = pd.to_numeric(df[col], errors="coerce").isna() & df[col].notna()
                if bad.any():
                    note = f"{int(bad.sum())} non-numeric values will be skipped"
            checks.append({"col": col, "status": "warning" if note else "found", "note": note or "Found"})
        elif _norm(col) in by_norm:
            ok = False
            checks.append({"col": col, "status": "missing",
                           "note": f"Missing. Found '{by_norm[_norm(col)]}' — rename the header?"})
        else:
            ok = False
            checks.append({"col": col, "status": "missing", "note": "Missing"})
    if len(df) == 0:
        ok = False
        checks.append({"col": "(rows)", "status": "missing", "note": "File has no data rows"})
    return ValidationResult(ok=ok, checks=checks)


def run_audit(df: pd.DataFrame, t: Thresholds | None = None) -> AuditResult:
    t = t or Thresholds()
    df = df.copy()
    total_rows = len(df)

    coerced = {}
    for c in NUMERIC_COLUMNS:
        before = df[c].notna().sum()
        df[c] = pd.to_numeric(df[c], errors="coerce")
        coerced[c] = int(before - df[c].notna().sum())

    # Rows without a usable ID can't be tracked or reviewed; drop and count them.
    no_id = df["EmployeeNumber"].isna()
    df = df[~no_id]
    dup_mask = df["EmployeeNumber"].duplicated(keep="first")
    duplicate_ids = int(dup_mask.sum())
    df = df[~dup_mask].copy()
    df["EmployeeNumber"] = df["EmployeeNumber"].astype(int)

    df["AnnualSalary"] = df["MonthlyIncome"] * 12
    df.loc[df["AnnualSalary"] <= 0, "AnnualSalary"] = pd.NA
    df["missing_salary"] = df["AnnualSalary"].isna()
    # Any other required value that is blank or non-numeric: skip the row, report the count.
    other = [c for c in REQUIRED_COLUMNS if c not in ("EmployeeNumber", "MonthlyIncome")]
    df["invalid"] = ~df["missing_salary"] & df[other].isna().any(axis=1)
    df["cohort_key"] = df["JobRole"].astype(str) + "|" + df["JobLevel"].astype("Int64").astype(str) + "|" + df["Department"].astype(str)

    valid = df[~df["missing_salary"] & ~df["invalid"]]
    g = valid.groupby("cohort_key")["AnnualSalary"]
    cohorts = pd.DataFrame({
        "n": g.size(), "min": g.min(), "p25": g.quantile(0.25),
        "median": g.median(), "p75": g.quantile(0.75), "max": g.max(),
    })
    df = df.join(cohorts, on="cohort_key")
    df["excluded"] = ~df["missing_salary"] & ~df["invalid"] & (df["n"].fillna(0) < t.min_cohort)
    df["evaluated"] = ~df["missing_salary"] & ~df["invalid"] & ~df["excluded"]
    df["ratio"] = (df["AnnualSalary"] / df["median"]).where(df["evaluated"])
    df["gap"] = (df["AnnualSalary"] - df["median"]).where(df["evaluated"])

    rows = []
    for _, e in df[df["evaluated"]].iterrows():
        r, sal, med = e["ratio"], e["AnnualSalary"], e["median"]
        pc = round((1 - r) * 100)
        cl = f"{e['JobRole']} L{int(e['JobLevel'])}, {e['Department']}, n={int(e['n'])}"
        if r < t.under_med:
            rows.append((e["EmployeeNumber"], "under", "High" if r < t.under_high else "Medium", med - sal,
                         f"Paid {pc}% below the cohort median of ${med:,.0f} ({cl})."))
        if r > t.over_low:
            rows.append((e["EmployeeNumber"], "over", "Low", 0.0,
                         f"Paid {round((r - 1) * 100)}% above the cohort median; ${sal - e['p75']:,.0f} over the 75th percentile. "
                         "Check for a missing level change or a data entry error."))
        if e["YearsSinceLastPromotion"] == 0 and e["PercentSalaryHike"] < t.promo_min_raise and e["JobLevel"] >= 2:
            rows.append((e["EmployeeNumber"], "promo", "High",
                         round(sal * (t.promo_expected_raise - e["PercentSalaryHike"]) / 100),
                         f"Promoted within the last 12 months with a {e['PercentSalaryHike']:g}% raise. "
                         f"Expected minimum on promotion is {t.promo_expected_raise:g}% (configurable)."))
        if e["YearsAtCompany"] >= t.compression_tenure and t.under_med <= r < t.compression_ratio:
            rows.append((e["EmployeeNumber"], "comp", "Medium", med - sal,
                         f"{int(e['YearsAtCompany'])} years tenure but paid {pc}% below the cohort median."))

    flags = pd.DataFrame(rows, columns=["EmployeeNumber", "rule", "severity", "impact", "reason"])
    if not flags.empty:
        flags["rule_name"] = flags["rule"].map(RULE_NAMES)
        agg = flags.assign(rank=flags["severity"].map(SEV_RANK)).groupby("EmployeeNumber").agg(
            flag_count=("rule", "size"),
            rules=("rule", list),
            top_rank=("rank", "max"),
            exposure=("impact", "sum"),
        )
        agg["top_severity"] = agg["top_rank"].map({v: k for k, v in SEV_RANK.items()})
        over = flags[flags["rule"] == "over"].set_index("EmployeeNumber")
        df = df.join(agg.drop(columns="top_rank"), on="EmployeeNumber")
        df["above_band"] = (df["AnnualSalary"] - df["p75"]).where(df["EmployeeNumber"].isin(over.index), 0)
    else:
        df["flag_count"], df["rules"], df["exposure"], df["top_severity"], df["above_band"] = 0, None, 0.0, None, 0.0
    df["flag_count"] = df["flag_count"].fillna(0).astype(int)
    df["exposure"] = df["exposure"].fillna(0.0)
    df["above_band"] = df["above_band"].fillna(0.0)

    return AuditResult(
        employees=df.reset_index(drop=True), flags=flags, cohorts=cohorts.reset_index(),
        skipped_missing_salary=int(df["missing_salary"].sum()),
        excluded_small_cohort=int(df["excluded"].sum()),
        duplicate_ids=duplicate_ids, coerced_values=coerced,
        skipped_invalid=int(df["invalid"].sum()) + int(no_id.sum()),
        total_rows=total_rows,
    )


def summary(res: AuditResult) -> dict:
    e = res.employees
    flagged = e[e["flag_count"] > 0]
    evaluated = int(e["evaluated"].sum())
    high = res.flags[res.flags["severity"] == "High"] if not res.flags.empty else res.flags
    return {
        "total": len(e),
        "evaluated": evaluated,
        "flagged": len(flagged),
        "flagged_pct": (len(flagged) / evaluated * 100) if evaluated else 0.0,
        "exposure": float(flagged["exposure"].sum()),        # excludes above-band by construction
        "exposure_people": int((flagged["exposure"] > 0).sum()),
        "high_flags": len(high),
        "above_band_total": float(e["above_band"].sum()),
        "above_band_people": int((e["above_band"] > 0).sum()),
        "cohorts": int((res.cohorts["n"] >= 5).sum()) if not res.cohorts.empty else 0,
        "total_rows": res.total_rows or len(e),
        "skipped_missing_salary": res.skipped_missing_salary,
        "skipped_invalid": res.skipped_invalid,
        "excluded_small_cohort": res.excluded_small_cohort,
        "duplicate_ids": res.duplicate_ids,
    }
