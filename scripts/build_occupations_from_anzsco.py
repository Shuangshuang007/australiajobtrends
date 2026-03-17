"""
Build data_abs/occupations_combined.csv with one row per ANZSCO Unit Group (~364 rows).

Reads ANZSCO structure from:
  1. data_abs/anzsco.csv (if present; e.g. from nzherald/ANZSCO inst/extdata/anzsco.csv)
  2. Or downloads from https://raw.githubusercontent.com/nzherald/ANZSCO/master/inst/extdata/anzsco.csv

Each row in the CSV is occupation-level; we deduplicate by Unit.Group.Code to get
one row per Unit Group. Category = Sub-Major (2-digit) slug for treemap grouping.
Leaves num_jobs_2024, median_pay_annual, outlook_pct, entry_education empty. Run merge_real_data.py after downloading JSA/ABS files to fill with real data only.

Usage (from Job Outlook Australia folder):
  python scripts/build_occupations_from_anzsco.py
"""

import csv
import os
import re
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
DATA_ABS = os.path.join(BASE_DIR, "data_abs")
OUT_CSV = os.path.join(DATA_ABS, "occupations_combined.csv")
ANZSCO_CSV_URL = "https://raw.githubusercontent.com/nzherald/ANZSCO/master/inst/extdata/anzsco.csv"
LOCAL_ANZSCO = os.path.join(DATA_ABS, "anzsco.csv")


def slugify(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (s or "").lower())
    s = re.sub(r"[-\s]+", "-", s).strip("-")
    return s[:48] if s else "other"


def sub_major_to_category(code: str, name: str) -> str:
    """Category for treemap: 2-digit + short slug."""
    code = (code or "").strip()
    slug = slugify(name or "")
    return f"{code}-{slug}" if code else slug or "other"


# No placeholder/fabricated data. Fill num_jobs_2024, median_pay_annual, outlook_pct,
# entry_education via merge_real_data.py using JSA and ABS downloads (see README_REAL_DATA.md).


def main():
    os.makedirs(DATA_ABS, exist_ok=True)

    csv_path = LOCAL_ANZSCO
    if not os.path.exists(csv_path):
        print(f"Downloading ANZSCO from {ANZSCO_CSV_URL} ...")
        try:
            urllib.request.urlretrieve(ANZSCO_CSV_URL, csv_path)
        except Exception as e:
            print(f"Download failed: {e}")
            print(f"Save anzsco.csv to {DATA_ABS} (e.g. from nzherald/ANZSCO inst/extdata/anzsco.csv) and run again.")
            return
    else:
        print(f"Using local {csv_path}")

    # One row per Unit Group (4-digit code)
    by_unit = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ug_code = (row.get("Unit.Group.Code") or "").strip()
            if not ug_code or ug_code in by_unit:
                continue
            title = (row.get("Unit.Group") or "").strip()
            sm_code = (row.get("Sub.Major.Group.Code") or "").strip()
            sm_name = (row.get("Sub.Major.Group") or "").strip()
            if not title:
                continue
            by_unit[ug_code] = {
                "title": title,
                "sub_major_code": sm_code,
                "sub_major_name": sm_name,
            }

    rows = []
    for ug_code, v in sorted(by_unit.items()):
        category = sub_major_to_category(v["sub_major_code"], v["sub_major_name"])
        rows.append({
            "title": v["title"],
            "category": category,
            "anzsco_code": ug_code,
            "num_jobs_2024": "",
            "median_pay_annual": "",
            "outlook_pct": "",
            "entry_education": "",
            "url": "https://www.abs.gov.au/statistics/classifications/anzsco-australian-and-new-zealand-standard-classification-occupations",
        })

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "title", "category", "anzsco_code", "num_jobs_2024", "median_pay_annual",
            "outlook_pct", "entry_education", "url",
        ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} Unit Groups to {OUT_CSV}")
    print("Next: run make_csv_au.py then build_site_data_au.py to refresh the site.")


if __name__ == "__main__":
    main()
