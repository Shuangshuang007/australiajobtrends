"""
Build site/data.json for Australia from occupations_au.csv (and optional scores_au.json).

Same logic as build_site_data.py but reads:
  - occupations_au.csv (from make_csv_au.py)
  - scores_au.json (optional; from score_au.py if you run LLM scoring for AU occupations)

Writes site/data.json so the same site/index.html works. Run this in the
Job Outlook Australia folder after make_csv_au.py (and optionally score_au.py).

Usage:
  python build_site_data_au.py
"""

import csv
import json
import os

SCORES_PATH = "scores_au.json"
CSV_PATH = "occupations_au.csv"
OUT_PATH = "site/data.json"

# ANZSCO Sub-Major group display names (for treemap category labels)
SUBMAJOR_LABELS = {
    "11": "Chief Executives, General Managers and Legislators",
    "12": "Farmers and Farm Managers",
    "13": "Specialist Managers",
    "14": "Hospitality, Retail and Service Managers",
    "19": "Other Managers",
    "21": "Arts and Media Professionals",
    "22": "Business, Human Resource and Marketing Professionals",
    "23": "Design, Engineering, Science and Transport Professionals",
    "24": "Education Professionals",
    "25": "Health Professionals",
    "26": "ICT Professionals",
    "27": "Legal, Social and Welfare Professionals",
    "31": "Engineering, ICT and Science Technicians",
    "32": "Automotive and Engineering Trades Workers",
    "33": "Construction Trades Workers",
    "34": "Electrotechnology and Telecommunications Trades Workers",
    "35": "Food Trades Workers",
    "36": "Skilled Animal and Horticultural Workers",
    "39": "Other Technicians and Trades Workers",
    "41": "Health and Welfare Support Workers",
    "42": "Carers and Aides",
    "43": "Hospitality Workers",
    "44": "Protective Service Workers",
    "45": "Sports and Personal Service Workers",
    "49": "Other Community and Personal Service Workers",
    "51": "Office Managers and Program Administrators",
    "52": "Personal Assistants and Secretaries",
    "53": "General Clerical Workers",
    "54": "Inquiry Clerks and Receptionists",
    "55": "Numerical Clerks",
    "56": "Clerical and Office Support Workers",
    "59": "Other Clerical and Administrative Workers",
    "61": "Sales Representatives and Agents",
    "62": "Sales Assistants and Salespersons",
    "63": "Sales Support Workers",
    "69": "Other Sales Workers",
    "71": "Machine and Stationary Plant Operators",
    "72": "Mobile Plant Operators",
    "73": "Road and Rail Drivers",
    "74": "Storepersons",
    "79": "Other Machinery Operators and Drivers",
    "81": "Cleaners and Laundry Workers",
    "82": "Construction and Mining Labourers",
    "83": "Factory Process Workers",
    "84": "Farm, Forestry and Garden Workers",
    "85": "Food Preparation Assistants",
    "86": "Storepersons",
    "89": "Other Labourers",
}


def category_label(category_slug: str) -> str:
    """Return human-readable label for treemap grouping (Sub-Major name)."""
    if not category_slug:
        return "Other"
    code = category_slug.split("-")[0] if "-" in category_slug else category_slug[:2]
    if code in SUBMAJOR_LABELS:
        return SUBMAJOR_LABELS[code]
    # Fallback: title-case the slug (after "NN-")
    rest = category_slug.split("-", 1)[-1] if "-" in category_slug else category_slug
    return rest.replace("-", " ").title()


def main():
    scores = {}
    if os.path.exists(SCORES_PATH):
        with open(SCORES_PATH) as f:
            scores_list = json.load(f)
        scores = {s["slug"]: s for s in scores_list}
        print(f"Loaded {len(scores)} scores from {SCORES_PATH}")
    else:
        print(f"No {SCORES_PATH}; exposure layer will be empty.")

    if not os.path.exists(CSV_PATH):
        print(f"Run make_csv_au.py first to create {CSV_PATH}")
        return

    with open(CSV_PATH) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # JSA occupation profile base (outlook 2025 actual + pay + employment source)
    JSA_PROFILE_BASE = "https://www.jobsandskills.gov.au/data/occupation-and-industry-profiles/occupations"
    data = []
    for row in rows:
        slug = row.get("slug", "")
        score = scores.get(slug, {})
        cat = row.get("category", "")
        anzsco = (row.get("soc_code") or row.get("anzsco_code") or "").strip()
        # Link to JSA occupation profile (source for 2025 Actual, pay, employment)
        if anzsco == "1311":
            url = "https://www.jobsandskills.gov.au/data/occupation-and-industry-profiles/occupations/1311-advertising-public-relations-and-sales-manager"
        else:
            url = f"{JSA_PROFILE_BASE}/{anzsco}-{slug}" if (anzsco and slug) else row.get("url", "")
        data.append({
            "title": row.get("title", ""),
            "slug": slug,
            "category": cat,
            "category_label": category_label(cat),
            "pay": int(row["median_pay_annual"]) if row.get("median_pay_annual") else None,
            "jobs": int(row["num_jobs_2024"]) if row.get("num_jobs_2024") else None,
            "outlook": int(row["outlook_pct"]) if row.get("outlook_pct") else None,
            "outlook_2025_actual": int(row["outlook_pct_2025_actual"]) if row.get("outlook_pct_2025_actual") else None,
            "outlook_ai": int(row["outlook_pct_ai"]) if row.get("outlook_pct_ai") else None,
            "outlook_desc": row.get("outlook_desc", ""),
            "education": row.get("entry_education", ""),
            "exposure": score.get("exposure"),
            "exposure_rationale": score.get("rationale"),
            "url": url,
        })

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(data, f)

    print(f"Wrote {len(data)} occupations to {OUT_PATH}")
    total_jobs = sum(d["jobs"] for d in data if d["jobs"])
    print(f"Total jobs: {total_jobs:,}")


if __name__ == "__main__":
    main()
