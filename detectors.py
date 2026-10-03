"""PayGuard AI — rule-based detectors for payroll anomalies.

Pure pandas + numpy. Reads the IBM HR dataset, derives cohort stats
(JobRole + JobLevel), and runs four rules: underpayment, overpayment,
compression, and promotion/raise mismatch.
"""

from __future__ import annotations

import pandas as pd

from schema import (
    COL_ANNUAL_SALARY, COL_COHORT, COL_DEPT, COL_ID, COL_INCOME_MONTHLY,
    COL_LEVEL, COL_NAME, COL_PERCENT_HIKE, COL_ROLE, COL_TENURE,
    COL_YEARS_SINCE_PROMO, COMPRESSION_NEW_HIRE_YEARS,
    COMPRESSION_TENURED_YEARS, DATA_PATH, Flag, MIN_COHORT_SIZE,
    MISMATCH_HIKE_THRESHOLD_PCT, MISMATCH_PROMO_WINDOW_YEARS,
    RULE_COMPRESSION, RULE_META, RULE_MISMATCH, RULE_OVERPAY, RULE_UNDERPAY,
    SEVERITY_RANK, UNDERPAY_TENURE_YEARS, synthesize_name,
)


def _fmt(x: float) -> str:
    return f"${int(round(x)):,}"


def load_employees() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH)
    df[COL_ANNUAL_SALARY] = df[COL_INCOME_MONTHLY].astype(int) * 12
    df[COL_NAME] = df[COL_ID].map(synthesize_name)
    df[COL_COHORT] = df[COL_ROLE].astype(str) + " L" + df[COL_LEVEL].astype(str)
    return df


def cohort_stats(df: pd.DataFrame) -> pd.DataFrame:
    grouped = df.groupby(COL_COHORT)[COL_ANNUAL_SALARY]
    stats = pd.DataFrame({
        "size": grouped.size(),
        "median": grouped.median(),
        "Q1": grouped.quantile(0.25, interpolation="linear"),
        "Q3": grouped.quantile(0.75, interpolation="linear"),
    })
    stats["IQR"] = stats["Q3"] - stats["Q1"]
    stats["lower_fence"] = stats["median"] - 1.5 * stats["IQR"]
    stats["upper_fence"] = stats["median"] + 1.5 * stats["IQR"]
    stats = stats[stats["size"] >= MIN_COHORT_SIZE].copy()
    return stats


def _cohort_label(row: pd.Series) -> tuple[str, int]:
    return str(row[COL_ROLE]), int(row[COL_LEVEL])


def detect_underpayment(df: pd.DataFrame, stats: pd.DataFrame) -> list[Flag]:
    flags: list[Flag] = []
    sev = RULE_META[RULE_UNDERPAY]["severity"]
    merged = df.merge(stats, left_on=COL_COHORT, right_index=True, how="inner")
    hits = merged[
        (merged[COL_ANNUAL_SALARY] < merged["lower_fence"])
        & (merged[COL_TENURE] > UNDERPAY_TENURE_YEARS)
    ]
    for _, row in hits.iterrows():
        role, level = _cohort_label(row)
        salary = int(row[COL_ANNUAL_SALARY])
        fence = int(round(row["lower_fence"]))
        n = int(row["size"])
        reason = (
            f"Salary {_fmt(salary)} is below cohort fence of {_fmt(fence)} "
            f"({role} L{level}, n={n})."
        )
        flags.append(Flag(
            employee_id=int(row[COL_ID]),
            rule=RULE_UNDERPAY,
            severity=sev,
            reason=reason,
            evidence={
                "salary": salary,
                "cohort_median": int(round(row["median"])),
                "lower_fence": fence,
                "iqr": int(round(row["IQR"])),
                "cohort_size": n,
                "tenure": int(row[COL_TENURE]),
            },
        ))
    return flags


def detect_overpayment(df: pd.DataFrame, stats: pd.DataFrame) -> list[Flag]:
    flags: list[Flag] = []
    sev = RULE_META[RULE_OVERPAY]["severity"]
    merged = df.merge(stats, left_on=COL_COHORT, right_index=True, how="inner")
    hits = merged[merged[COL_ANNUAL_SALARY] > merged["upper_fence"]]
    for _, row in hits.iterrows():
        role, level = _cohort_label(row)
        salary = int(row[COL_ANNUAL_SALARY])
        fence = int(round(row["upper_fence"]))
        n = int(row["size"])
        reason = (
            f"Salary {_fmt(salary)} is above cohort fence of {_fmt(fence)} "
            f"({role} L{level}, n={n})."
        )
        flags.append(Flag(
            employee_id=int(row[COL_ID]),
            rule=RULE_OVERPAY,
            severity=sev,
            reason=reason,
            evidence={
                "salary": salary,
                "cohort_median": int(round(row["median"])),
                "upper_fence": fence,
                "iqr": int(round(row["IQR"])),
                "cohort_size": n,
            },
        ))
    return flags


def detect_compression(df: pd.DataFrame, stats: pd.DataFrame) -> list[Flag]:
    flags: list[Flag] = []
    sev = RULE_META[RULE_COMPRESSION]["severity"]
    qualifying = set(stats.index)
    df_q = df[df[COL_COHORT].isin(qualifying)]
    for cohort, group in df_q.groupby(COL_COHORT):
        tenured = group[group[COL_TENURE] >= COMPRESSION_TENURED_YEARS]
        if len(tenured) < 2:
            continue
        new_hires = group[group[COL_TENURE] <= COMPRESSION_NEW_HIRE_YEARS]
        if new_hires.empty:
            continue
        tenured_median = int(round(tenured[COL_ANNUAL_SALARY].median()))
        tenured_mean_tenure = int(round(tenured[COL_TENURE].mean()))
        n_tenured = len(tenured)
        for _, hire in new_hires.iterrows():
            my_salary = int(hire[COL_ANNUAL_SALARY])
            if my_salary <= tenured_median:
                continue
            my_tenure = int(hire[COL_TENURE])
            n_below = int((tenured[COL_ANNUAL_SALARY] < my_salary).sum())
            reason = (
                f"New hire ({_fmt(my_salary)}, {my_tenure}y) earns more than "
                f"{n_below}/{n_tenured} tenured peers (median {_fmt(tenured_median)}, "
                f"avg {tenured_mean_tenure}y)."
            )
            flags.append(Flag(
                employee_id=int(hire[COL_ID]),
                rule=RULE_COMPRESSION,
                severity=sev,
                reason=reason,
                evidence={
                    "tenured_median": tenured_median,
                    "tenured_mean_tenure": tenured_mean_tenure,
                    "n_tenured_peers": n_tenured,
                    "n_peers_below": n_below,
                    "my_tenure": my_tenure,
                    "salary_delta": my_salary - tenured_median,
                },
            ))
    return flags


def detect_mismatch(df: pd.DataFrame) -> list[Flag]:
    flags: list[Flag] = []
    sev = RULE_META[RULE_MISMATCH]["severity"]
    hits = df[
        (df[COL_YEARS_SINCE_PROMO] <= MISMATCH_PROMO_WINDOW_YEARS)
        & (df[COL_PERCENT_HIKE] < MISMATCH_HIKE_THRESHOLD_PCT)
    ]
    for _, row in hits.iterrows():
        yrs = int(row[COL_YEARS_SINCE_PROMO])
        hike = int(row[COL_PERCENT_HIKE])
        reason = (
            f"Promoted {yrs} years ago but only received a {hike}% hike."
        )
        flags.append(Flag(
            employee_id=int(row[COL_ID]),
            rule=RULE_MISMATCH,
            severity=sev,
            reason=reason,
            evidence={
                "years_since_promotion": yrs,
                "percent_hike": hike,
            },
        ))
    return flags


def run_all(df: pd.DataFrame) -> pd.DataFrame:
    stats = cohort_stats(df)
    all_flags: list[Flag] = []
    all_flags.extend(detect_underpayment(df, stats))
    all_flags.extend(detect_overpayment(df, stats))
    all_flags.extend(detect_compression(df, stats))
    all_flags.extend(detect_mismatch(df))

    if not all_flags:
        return pd.DataFrame(columns=[
            "employee_id", "name", "role", "level", "department",
            "annual_salary", "rule", "severity", "reason", "evidence",
        ])

    lookup = df.set_index(COL_ID)
    rows = []
    for f in all_flags:
        emp = lookup.loc[f.employee_id]
        rows.append({
            "employee_id": f.employee_id,
            "name": emp[COL_NAME],
            "role": emp[COL_ROLE],
            "level": int(emp[COL_LEVEL]),
            "department": emp[COL_DEPT],
            "annual_salary": int(emp[COL_ANNUAL_SALARY]),
            "rule": f.rule,
            "severity": f.severity,
            "reason": f.reason,
            "evidence": f.evidence,
        })
    out = pd.DataFrame(rows)
    out["evidence"] = out["evidence"].astype(object)
    return out


def total_exposure(flagged_df: pd.DataFrame, stats: pd.DataFrame) -> int:
    if flagged_df.empty:
        return 0
    df = flagged_df.copy()
    df["_sev_rank"] = df["severity"].map(SEVERITY_RANK)
    df = df.sort_values("_sev_rank", ascending=False)
    unique = df.drop_duplicates(subset=["employee_id"], keep="first")
    cohort_lookup = (unique["role"].astype(str) + " L" + unique["level"].astype(str))
    medians = cohort_lookup.map(stats["median"])
    deltas = (unique["annual_salary"] - medians).abs()
    deltas = deltas.dropna()
    return int(round(deltas.sum()))


if __name__ == "__main__":
    df = load_employees()
    stats = cohort_stats(df)
    flags = run_all(df)
    exposure = total_exposure(flags, stats)
    print(f"Loaded {len(df)} employees across {df['Cohort'].nunique()} cohorts")
    print(f"Qualifying cohorts (n>={MIN_COHORT_SIZE}): {len(stats)}")
    print(f"Total flags: {len(flags)} across {flags['employee_id'].nunique()} employees")
    print(flags.groupby('rule').size().to_string())
    print(f"Estimated exposure: ${exposure:,}")
