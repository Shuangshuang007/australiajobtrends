# Australia Job Market Visualizer — Data & structure

This folder is an **Australia adaptation** of the US (BLS) version: same front-end and interaction, different data sources and processing scripts.

**Terminology:** Occupations use **ANZSCO/OSCA**; pay uses **AUD** and **median full-time ordinary time earnings**; skill/education use **AQF** and **ANZSCO skill level**.  
**Alignment with US version:** Unit Group granularity (364); views like "Outlook by education" match the US; data sources and field mapping are documented in **`DATA_SOURCES_AU.md`** (if present). Colour scale matches the US (red = Declining, green = Growing; pay 25K–250K scale, currency A$).  
**Data:** Employment, pay, outlook, and education use real official data only.  
**Input:** `make_csv_au.py` reads `data_abs/occupations_combined.csv` (or `../australia/occupations_combined.csv`).

---

## Data sources (Australia)

### 1. ABS (Australian Bureau of Statistics) — main source (analogous to US BLS)

- **Labour Force, Australia, Detailed** (6291.0.55.001): employment by occupation (ANZSCO/OSCA), industry, region.  
  <https://www.abs.gov.au/statistics/labour/employment-and-unemployment/labour-force-australia-detailed>
- **OSCA 2024** (occupation classification):  
  <https://www.abs.gov.au/statistics/classifications/osca-occupation-standard-classification-australia/2024-version-1-0/data-downloads>

Use `data_abs/` for downloaded ABS files. `make_csv_au.py` reads `data_abs/occupations_combined.csv` and produces `occupations_au.csv` in the same shape as the US `occupations.csv`.

### 2. Jobs and Skills Australia (JSA)

- Occupation and industry profiles, employment projections.  
  <https://www.jobsandskills.gov.au/data/occupation-and-industry-profiles>

---

## Quick start (sample data)

A sample CSV is provided: `data_abs/occupations_combined_sample.csv`. Copy it to `data_abs/occupations_combined.csv` if needed, then:

```bash
python3 make_csv_au.py
python3 build_site_data_au.py
cd site && python3 -m http.server 8000
```

Open http://localhost:8000 to view the Australia treemap. Replace `data_abs/occupations_combined.csv` with real ABS/JSA data for production.

---

## Folder structure

- **data_abs/** — Input data (occupations_combined.csv, outlook JSON, etc.)
- **make_csv_au.py** — Builds `occupations_au.csv` from data_abs
- **score_au.py** — Optional: LLM AI Exposure scoring → `scores_au.json`
- **build_site_data_au.py** — Merges CSV + scores → `site/data.json`
- **site/** — Static treemap (`index.html` + `data.json`)
