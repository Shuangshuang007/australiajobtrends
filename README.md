# Australia Job Market Visualizer

**Original work:** [US Job Market Visualizer](https://karpathy.ai/jobs/) by [Andrej Karpathy](https://github.com/karpathy/jobs) — live at **[karpathy.ai/jobs](https://karpathy.ai/jobs)**, source at **[github.com/karpathy/jobs](https://github.com/karpathy/jobs)**. Please visit the original first.

This repository is an **Australia adaptation** of that project: same structure and style, using Australian sources (Jobs and Skills Australia, ABS, ANZSCO). This is not a report, a paper, or a serious economic publication — it is a development tool for exploring Australian labour market data visually.

**Live demo (this adaptation):** [heraai.one/trends](https://heraai.one/trends) · **This repo:** [github.com/Shuangshuang007/australiajobtrends](https://github.com/Shuangshuang007/australiajobtrends)

---

## What's here

Australian official data covers **hundreds of occupations** (ANZSCO unit groups) with employment, median full-time earnings, skill level, and growth outlook. We built an interactive treemap visualization where each rectangle's **area** is proportional to total employment and **color** shows the selected metric — toggle between growth outlook (2025 actual / 2035 projection / AI scenario), median pay, skill requirement (ANZSCO), and AI exposure.

## LLM-powered coloring

The repo includes the same idea as the original: a pipeline for custom LLM prompts to score and color occupations by any criteria. You write a prompt, the LLM scores each occupation, and the treemap colors accordingly. The "Digital AI Exposure" layer is one example. See `score_au.py` for the prompt and scoring pipeline.

**What "AI Exposure" is NOT:**
- It does **not** predict that a job will disappear. High-exposure jobs are often reshaped, not replaced.
- It does **not** account for demand elasticity, latent demand, regulatory barriers, or social preferences for human workers.
- The scores are rough LLM estimates, not rigorous predictions.

## Data pipeline (Australia)

1. **Data** — `data_abs/occupations_combined.csv` (from ABS Labour Force, JSA Occupation profiles, ANZSCO). See `DATA_SOURCES_AU.md` and `README_AU.md` for sources and build steps.
2. **Tabulate** (`make_csv_au.py`) — Builds `occupations_au.csv` in the same shape as the US `occupations.csv`.
3. **Score** (`score_au.py`) — Optional. Sends occupation descriptions to an LLM for AI Exposure (0–10). Results in `scores_au.json`.
4. **Build site data** (`build_site_data_au.py`) — Merges CSV and scores into `site/data.json`.
5. **Website** (`site/index.html`) — Interactive treemap with four color layers: Outlook, Median Earnings, Skill Level, Digital AI Exposure.

## Key files

| File | Description |
|------|-------------|
| `occupations_au.csv` | Summary stats: pay, education/skill, job count, growth (from `make_csv_au.py`) |
| `scores_au.json` | AI exposure scores (0–10) with rationales, if you run `score_au.py` |
| `data_abs/` | Input data (occupations_combined.csv, ANZSCO/outlook JSON, etc.) |
| `pages_au/` | Clean Markdown per occupation (optional; used for LLM scoring) |
| `site/` | Static website (treemap) — `site/index.html` + `site/data.json` |

## Setup

```bash
# Python 3; optional: uv for deps
pip install -r requirements.txt   # or uv sync if you use uv
```

For LLM scoring, add a `.env` with your API key (e.g. OpenRouter):

```
OPENROUTER_API_KEY=your_key_here
```

## Usage

```bash
# 1. Ensure data_abs/occupations_combined.csv exists (see README_AU.md for data sources)
python make_csv_au.py

# 2. (Optional) Score AI exposure
python score_au.py

# 3. Build site data
python build_site_data_au.py

# 4. Serve the site locally
cd site && python -m http.server 8000
```

Open http://localhost:8000 to view the Australia Job Market Visualizer.

## Terminology and sources

- **Occupations:** ANZSCO unit groups (aligned with US granularity where possible).
- **Pay:** Median full-time ordinary time earnings (AUD). **Outlook:** Jobs and Skills Australia (JSA); 2025 actual and 2035 projections; optional AI scenario.
- **Skill / education:** ANZSCO skill level and AQF. See `AU_TERMINOLOGY.md` and `DATA_SOURCES_AU.md`.

## Credit

Original US version: **[US Job Market Visualizer](https://karpathy.ai/jobs/)** by Andrej Karpathy — [github.com/karpathy/jobs](https://github.com/karpathy/jobs). This Australia fork keeps the same structure, pipeline, and UI style; only data sources and scripts are adapted for Australian official statistics.
