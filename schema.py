"""Shared constants and column mapping for PayGuard AI.

Dataset: IBM HR Analytics Employee Attrition
Source columns are preserved; derived columns are added at load time.
"""

from dataclasses import dataclass
from pathlib import Path

DATA_PATH = Path(__file__).parent / "data" / "employees.csv"

COL_ID = "EmployeeNumber"
COL_ROLE = "JobRole"
COL_LEVEL = "JobLevel"
COL_DEPT = "Department"
COL_INCOME_MONTHLY = "MonthlyIncome"
COL_TENURE = "YearsAtCompany"
COL_YEARS_SINCE_PROMO = "YearsSinceLastPromotion"
COL_PERCENT_HIKE = "PercentSalaryHike"
COL_YEARS_IN_ROLE = "YearsInCurrentRole"
COL_GENDER = "Gender"
COL_AGE = "Age"
COL_ATTRITION = "Attrition"

COL_ANNUAL_SALARY = "AnnualSalary"
COL_NAME = "Name"
COL_COHORT = "Cohort"

MIN_COHORT_SIZE = 4
UNDERPAY_TENURE_YEARS = 1
COMPRESSION_NEW_HIRE_YEARS = 1
COMPRESSION_TENURED_YEARS = 2
MISMATCH_PROMO_WINDOW_YEARS = 2
MISMATCH_HIKE_THRESHOLD_PCT = 12

RULE_UNDERPAY = "underpayment"
RULE_OVERPAY = "overpayment"
RULE_COMPRESSION = "compression"
RULE_MISMATCH = "mismatch"

SEVERITY_HIGH = "High"
SEVERITY_MEDIUM = "Medium"
SEVERITY_LOW = "Low"

SEVERITY_RANK = {SEVERITY_HIGH: 3, SEVERITY_MEDIUM: 2, SEVERITY_LOW: 1}

RULE_META = {
    RULE_UNDERPAY: {"severity": SEVERITY_HIGH, "icon": "🔴", "label": "Underpayment"},
    RULE_OVERPAY: {"severity": SEVERITY_LOW, "icon": "🟡", "label": "Overpayment"},
    RULE_COMPRESSION: {"severity": SEVERITY_MEDIUM, "icon": "🟠", "label": "Salary Compression"},
    RULE_MISMATCH: {"severity": SEVERITY_HIGH, "icon": "🔵", "label": "Promotion / Raise Mismatch"},
}

SEVERITY_COLOR = {
    SEVERITY_HIGH: "#E74C3C",
    SEVERITY_MEDIUM: "#E67E22",
    SEVERITY_LOW: "#F1C40F",
}


@dataclass(frozen=True)
class Flag:
    employee_id: int
    rule: str
    severity: str
    reason: str
    evidence: dict


FIRST_NAMES = [
    "Priya", "Marcus", "Elena", "Jordan", "Aisha", "Daniel", "Mei", "Rafael",
    "Zara", "Omar", "Fatima", "Lucas", "Hiroshi", "Chen", "Amara", "Noah",
    "Isabella", "Dmitri", "Yara", "Kai", "Soo-min", "Theo", "Nadia", "Idris",
    "Camila", "Arjun", "Linh", "Maya", "Felix", "Ngozi", "Sven", "Rania",
    "Diego", "Anya", "Kenji", "Leila", "Mateo", "Tala", "Victor", "Yusuf",
    "Clara", "Rohan", "Ingrid", "Juno", "Taye", "Ava", "Bodhi", "Sana",
    "Ravi", "Nora",
]

LAST_NAMES = [
    "Shah", "Chen", "Vasquez", "Kim", "Okonkwo", "Reeves", "Tanaka", "Delgado",
    "Al-Rashid", "Hassan", "Nguyen", "Petrov", "Oyelaran", "Johansson", "Patel",
    "Garcia", "Bianchi", "Novak", "Khoury", "Park", "Takahashi", "Mendes",
    "Abara", "Rossi", "Singh", "Fitzgerald", "Olafsson", "Zhang", "Lindqvist",
    "Rahman", "Castellanos", "Baptiste", "Nakamura", "Haddad", "Jovanovic",
    "Ortega", "Choi", "Varga", "Wambui", "Barros", "Finch", "Dalgaard",
    "Kowalski", "Yilmaz", "Hernandez", "Osei", "Mori", "Kapoor", "Larsen",
    "Vega",
]


def synthesize_name(employee_id: int) -> str:
    first = FIRST_NAMES[employee_id % len(FIRST_NAMES)]
    last = LAST_NAMES[(employee_id * 7) % len(LAST_NAMES)]
    return f"{first} {last}"
