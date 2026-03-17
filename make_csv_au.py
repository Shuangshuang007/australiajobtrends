"""
Build occupations_au.csv for Australia from ABS (and optionally other) data.

Data sources (see README_AU.md and DATA_SOURCES_AU.md):
  1. ABS Labour Force, Australia, Detailed (employment by occupation)
  2. ABS OSCA / ANZSCO (occupation titles and structure); optional: hera_one/australia/ (or skill_sources/australia/) with OSCA xlsx
  3. Jobs and Skills Australia (JSA) Employment Projections for outlook_pct by occupation (4-digit ANZSCO)
  4. ANZSCO skill level → AQF for entry_education (Outlook by education)

This script reads from data_abs/ (or australia folder) and writes occupations_au.csv in the same
format as the US occupations.csv so build_site_data_au.py works.

Usage:
  python make_csv_au.py

Expected inputs (first found wins):
  - data_abs/occupations_combined.csv
  - ../australia/occupations_combined.csv  (when run from Job Outlook Australia/, uses hera_one/australia/)

Output:
  - occupations_au.csv (same columns as US: title, category, slug, soc_code, median_pay_annual, ...)
"""

import csv
import os
import re

# Same fieldnames as US make_csv.py so build_site_data.py works unchanged
FIELDNAMES = [
    "title", "category", "slug", "soc_code",
    "median_pay_annual", "median_pay_hourly",
    "entry_education", "work_experience", "training",
    "num_jobs_2024", "projected_employment_2034",
    "outlook_pct", "outlook_pct_2025_actual", "outlook_pct_ai",
    "outlook_desc", "employment_change",
    "url",
]


def slugify(title: str) -> str:
    """Same slug style as US: lowercase, spaces and punctuation to hyphens."""
    s = re.sub(r"[^\w\s-]", "", title.lower())
    s = re.sub(r"[-\s]+", "-", s).strip("-")
    return s or "occupation"


def load_from_combined_csv():
    """
    Read a pre-built data_abs/occupations_combined.csv.
    Expected columns (can have different names; we map below):
      title or occupation_title
      category or anzsco_major or occupation_group
      employment or num_jobs or employed
      median_pay_annual or median_earnings or wage (AUD)
      outlook_pct or growth_pct or projected_growth
      entry_education (optional)
      url (optional)
    """
    base = os.path.dirname(os.path.abspath(__file__)) or "."
    candidates = [
        os.path.join(base, "data_abs", "occupations_combined.csv"),
        os.path.join(base, "..", "australia", "occupations_combined.csv"),
    ]
    path = None
    for p in candidates:
        p = os.path.abspath(p)
        if os.path.exists(p):
            path = p
            break
    if path is None:
        return None

    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            # Normalise column names
            title = r.get("title") or r.get("occupation_title") or r.get("Occupation") or ""
            category = r.get("category") or r.get("anzsco_major") or r.get("occupation_group") or "other"
            jobs = r.get("num_jobs_2024") or r.get("employment") or r.get("employed") or r.get("Employed") or ""
            pay = r.get("median_pay_annual") or r.get("median_earnings") or r.get("wage") or r.get("Wage") or ""
            outlook = r.get("outlook_pct") or r.get("growth_pct") or r.get("projected_growth") or r.get("Outlook") or ""
            outlook_2025 = (r.get("outlook_pct_2025_actual") or "").strip()
            outlook_ai = (r.get("outlook_pct_ai") or "").strip()
            education = r.get("entry_education") or r.get("Education") or ""
            url = r.get("url") or r.get("URL") or ""

            if not title:
                continue
            try:
                jobs_int = int(str(jobs).replace(",", "")) if jobs else ""
            except ValueError:
                jobs_int = ""
            try:
                pay_int = int(str(pay).replace(",", "").replace("$", "")) if pay else ""
            except ValueError:
                pay_int = ""
            try:
                outlook_int = int(float(str(outlook).replace("%", ""))) if outlook else None
            except (ValueError, TypeError):
                outlook_int = None
            try:
                outlook_2025_int = int(float(str(outlook_2025).replace("%", ""))) if outlook_2025 else None
            except (ValueError, TypeError):
                outlook_2025_int = None
            try:
                outlook_ai_int = int(float(str(outlook_ai).replace("%", ""))) if outlook_ai else None
            except (ValueError, TypeError):
                outlook_ai_int = None

            rows.append({
                "title": title,
                "category": category.replace(" ", "-").lower()[:50],
                "slug": slugify(title),
                "soc_code": r.get("anzsco_code") or r.get("soc_code") or "",
                "median_pay_annual": str(pay_int) if pay_int else "",
                "median_pay_hourly": "",
                "entry_education": education,
                "work_experience": r.get("work_experience") or "",
                "training": r.get("training") or "",
                "num_jobs_2024": str(jobs_int) if jobs_int else "",
                "projected_employment_2034": r.get("projected_employment_2034") or "",
                "outlook_pct": str(outlook_int) if outlook_int is not None else "",
                "outlook_pct_2025_actual": str(outlook_2025_int) if outlook_2025_int is not None else "",
                "outlook_pct_ai": str(outlook_ai_int) if outlook_ai_int is not None else "",
                "outlook_desc": r.get("outlook_desc") or ("Faster than average" if outlook_int is not None and outlook_int > 5 else "Average") if outlook_int is not None else "",
                "employment_change": r.get("employment_change") or "",
                "url": url,
            })
    return rows


def main():
    os.makedirs("data_abs", exist_ok=True)

    rows = load_from_combined_csv()
    if not rows:
        print("No data_abs/occupations_combined.csv found.")
        print("To generate occupations_au.csv:")
        print("  1. Download ABS Labour Force Detailed (by occupation) and/or OSCA from README_AU.md links.")
        print("  2. Build a CSV with columns: title, category, num_jobs_2024, median_pay_annual, outlook_pct, (optional: entry_education, url).")
        print("  3. Save as data_abs/occupations_combined.csv and run this script again.")
        # Write empty CSV so structure exists
        with open("occupations_au.csv", "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
        print("Wrote empty occupations_au.csv.")
        return

    with open("occupations_au.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    total_jobs = sum(int(r["num_jobs_2024"]) for r in rows if r.get("num_jobs_2024"))
    print(f"Wrote {len(rows)} rows to occupations_au.csv (total jobs: {total_jobs:,})")
    for r in rows[:3]:
        print(f"  {r['title']}: {r['num_jobs_2024']} jobs, ${r['median_pay_annual']}/yr, {r['outlook_pct']}% outlook")


if __name__ == "__main__":
    main()
