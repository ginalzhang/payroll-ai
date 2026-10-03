"""Shared constants and column mapping for PayGuard AI.

Dataset: IBM HR Analytics Employee Attrition
Source columns are preserved; derived columns are added at load time.
"""

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
    # The id // 50 term spreads last names so names are unique for ids < 2,500
    # (the old id * 7 formula produced only 50 distinct names).
    n = len(FIRST_NAMES)
    first = FIRST_NAMES[employee_id % n]
    last = LAST_NAMES[(employee_id * 7 + employee_id // n) % len(LAST_NAMES)]
    return f"{first} {last}"
