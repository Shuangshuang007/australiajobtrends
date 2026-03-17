"""
Step 2 of AI Forecast: run GPT-5.1 (and gpt-5.1-2025-11-13) to produce AI-adjusted outlook.

Flow (AI_FORECAST_DESIGN.md):
  1. Macro first: model predicts total_employment_2035_ai_adjusted, total_decline_vs_official_pct.
  2. Top-down: per-occupation breakdown that sums to that total.
  3. Bottom-up: per-occupation independent prediction; we sum and compare to macro.
  4. Cross-check: reconcile and output one final version per model.
  5. Merge two models (median per occupation) → write data_abs/ai_forecast_outlook.json.

Requires: map_au_us_occupations.py run first (au_us_occupation_mapping.csv), occupations_combined.csv,
  pages_au/*.md, scores_au.json. Optional: .env.local for OPENAI_API_KEY.

Usage (from Job Outlook Australia folder):
  python scripts/ai_forecast_au.py --model gpt-5.1         # Run one model only; append to by_model.json
  python scripts/ai_forecast_au.py                         # Run all OpenAI models
  python scripts/ai_forecast_au.py --macro-only            # Macro step only
  python scripts/ai_forecast_au.py --dry-run               # Build input only (no API calls)
  Log lines use [HH:MM:SS]; each td/bu batch prints immediately.
"""

import csv
import json
import os
import re
import time
import argparse

try:
    import httpx
except ImportError:
    httpx = None

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
DATA_ABS = os.path.join(BASE_DIR, "data_abs")
AUSTRALIA_DIR = os.path.join(os.path.dirname(BASE_DIR), "australia")
REFERENCE_DIR = os.path.join(AUSTRALIA_DIR, "reference")
PAGES_AU = os.path.join(BASE_DIR, "pages_au")
SCORES_AU = os.path.join(BASE_DIR, "scores_au.json")
COMBINED_CSV = os.path.join(DATA_ABS, "occupations_combined.csv")
MAPPING_CSV = os.path.join(REFERENCE_DIR, "au_us_occupation_mapping.csv")
OUTPUT_JSON = os.path.join(DATA_ABS, "ai_forecast_outlook.json")

# JSA Table_3 Skill Level: Total May 2025 ~14.70M, May 2035 ~16.66M, 10-year ~13.3%
MACRO_OFFICIAL = {
    "employment_2025": 14_700_987,
    "employment_2035_official": 16_655_521,
    "growth_pct_official": 13.3,
}

# OpenAI only (OPENAI_API_KEY)
FORECAST_MODELS = [
    "gpt-5.1",
    "gpt-5.1-2025-11-13",
]
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
BY_MODEL_JSON = os.path.join(DATA_ABS, "ai_forecast_outlook_by_model.json")

# Occupation-type weighting and allocation rules. Type C = routine/compressible (default labour-losing).
# Injected into per-occupation prompts; reconcile step uses allocation logic, not simple balancing.
LOCAL_VS_GLOBAL_WEIGHTING = """
### Occupation Type and Signal Weighting (Required)

Classify each occupation implicitly and apply the correct weighting. You must create both labour winners and labour losers; do not spread positive growth broadly.

**Type A — Local / Policy-driven** (e.g. school teachers, nurses, aged care, social workers, public administration):
- Demand driven by demographics, regulation, public funding. Less sensitive to global labour cycles.
- Prioritise: Australian recent trend (o25), local demand, demographics, Australian official (o35). Use U.S. (us) only as weak reference.
- AI adjustment should be milder unless strong evidence exists.

**Type B — Global / Market-driven** (e.g. software engineering, product, marketing, design, finance, business ops):
- Demand influenced by global tech cycles; U.S. signal should carry much more weight.
- Prioritise: U.S. projection (us) as lead indicator; Australian recent (o25) as reality check. Discount Australian official (o35) if inconsistent with U.S. + AI trend.
- Apply stronger AI adjustment (both positive and negative).

**Type C — Routine / Compressible** (e.g. receptionists, general clerks, payroll clerks, checkout operators, bookkeepers, admin support, call centre / basic support):
- Default bias should be NEGATIVE unless local structural demand clearly offsets AI substitution.
- These occupations should be the main labour-losing pool. Do not treat them as "stable enough" without strong justification.
- Routine, repetitive, administrative, clerical, basic support, and low-complexity sales roles are default candidates for labour loss.

Rule: You are not averaging inputs. You are allocating a limited future labour pool. If some occupations gain strongly, others must stagnate or decline. Avoid "everything grows a bit". The growth rate for each occupation should follow from its type (A, B, or C) and the allocation story, not from matching any other country's distribution.
"""


def log(msg):
    """Print immediately, no buffering."""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_dotenv():
    try:
        from dotenv import load_dotenv as _load
        _load()
        _load(os.path.join(BASE_DIR, ".env.local"))
        _load(os.path.join(os.path.dirname(BASE_DIR), ".env.local"))
    except ImportError:
        pass


def slugify(title):
    import re
    s = re.sub(r"[^\w\s-]", "", title.lower())
    s = re.sub(r"[-\s]+", "-", s).strip("-")
    return s or "occupation"


def load_forecast_input():
    """Build { macro, occupations } for prediction. Each occupation: anzsco, title, slug, jobs, outlook_2035, outlook_2025_actual, education, pay, description_short, ai_exposure, us_projection_pct (from mapping)."""
    load_dotenv()
    macro = {**MACRO_OFFICIAL}

    if not os.path.exists(COMBINED_CSV):
        return None
    rows = []
    with open(COMBINED_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(dict(r))
    if not rows:
        return None

    mapping = {}
    if os.path.exists(MAPPING_CSV):
        with open(MAPPING_CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                mapping[r["anzsco_code"]] = r

    scores = {}
    if os.path.exists(SCORES_AU):
        with open(SCORES_AU) as f:
            for s in json.load(f):
                scores[s["slug"]] = s

    occupations = []
    for r in rows:
        code = (r.get("anzsco_code") or "").strip()
        title = (r.get("title") or "").strip()
        if not code or not title:
            continue
        slug = slugify(title)
        desc = ""
        md_path = os.path.join(PAGES_AU, f"{slug}.md")
        if os.path.exists(md_path):
            with open(md_path, encoding="utf-8") as f:
                desc = f.read()
            if len(desc) > 800:
                desc = desc[:800] + "..."
        map_row = mapping.get(code, {})
        try:
            us_pct = float(map_row.get("us_projection_pct") or 0) if map_row.get("us_projection_pct") else None
        except (TypeError, ValueError):
            us_pct = None
        occ = {
            "anzsco_code": code,
            "title": title,
            "slug": slug,
            "jobs": int(r["num_jobs_2024"]) if r.get("num_jobs_2024") else None,
            "outlook_2035": int(r["outlook_pct"]) if r.get("outlook_pct") else None,
            "outlook_2025_actual": int(r["outlook_pct_2025_actual"]) if r.get("outlook_pct_2025_actual") else None,
            "education": (r.get("entry_education") or "").strip(),
            "pay": int(r["median_pay_annual"]) if r.get("median_pay_annual") else None,
            "description_short": desc.strip(),
            "ai_exposure": scores.get(slug, {}).get("exposure"),
            "us_projection_pct": us_pct,
        }
        occupations.append(occ)
    return {"macro": macro, "occupations": occupations}


def build_macro_prompt(data):
    macro = data["macro"]
    n_occ = len(data["occupations"])
    total_jobs = sum(o.get("jobs") or 0 for o in data["occupations"])
    return f"""You are a labour market strategy analyst. Focus on Australia.

Official Australian employment (JSA):
- 2025 total employment: {macro['employment_2025']:,}
- 2035 official projection: {macro['employment_2035_official']:,}
- Official 10-year growth: {macro['growth_pct_official']}%

We have {n_occ} occupations in the dataset; their current employment sum is about {total_jobs:,}.

Context: Australian employment mix includes local/policy-driven sectors (education, health, aged care, government), global/market-driven sectors (tech, business, design), and routine/compressible roles (admin, clerical, support). Aggregate growth should reflect labour reallocation: some sectors gain, others stagnate or decline; the total can be lower than official while the distribution shifts sharply.

Assume that under AI adoption, total labour demand growth by 2035 may be LOWER than the official projection (productivity gains, automation, etc.). Your task is to state:
1. Your predicted total Australian employment in 2035 (number).
2. The implied decline vs official (e.g. "2 percentage points lower growth" or "X% below official 2035 level").
3. Short reasoning (2–4 sentences).

Respond with ONLY a JSON object, no other text:
{{
  "total_employment_2035_ai_adjusted": <number>,
  "total_decline_vs_official_pct": <number, e.g. -2.5 meaning 2.5 pp below official growth>,
  "reasoning_macro": "<2-4 sentences>"
}}"""


def _api_url_headers_model(model, api_key):
    """Return (url, headers, model_id) for OpenAI. Uses OPENAI_API_KEY."""
    return OPENAI_API_URL, {"Authorization": f"Bearer {api_key}"}, model


def call_macro(client, api_key, model, data):
    prompt = build_macro_prompt(data)
    url, headers, model_id = _api_url_headers_model(model, api_key)
    resp = client.post(
        url,
        headers=headers,
        json={
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        },
        timeout=90,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = re.sub(r"^```\w*\n?", "", content)
        content = re.sub(r"\n?```\s*$", "", content)
    return json.loads(content)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default=None, help="Only run this model (e.g. gpt-5.1). Saves/merges with by_model.json.")
    parser.add_argument("--suffix", type=str, default=None, help="Save to separate files with suffix (e.g. kimi -> ai_forecast_*_kimi.json). Does not overwrite default files.")
    parser.add_argument("--macro-only", action="store_true", help="Run only macro step")
    parser.add_argument("--dry-run", action="store_true", help="Build input only, no API")
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    models_to_run = [args.model] if args.model else FORECAST_MODELS
    if args.model and args.model not in FORECAST_MODELS:
        log(f"Unknown model '{args.model}'. Available: {FORECAST_MODELS}")
        return

    data = load_forecast_input()
    if not data:
        log(f"Missing {COMBINED_CSV} or empty. Run merge_real_data.py first.")
        return
    log(f"Loaded {len(data['occupations'])} occupations, macro official 2035={data['macro']['employment_2035_official']:,}")

    if args.dry_run:
        log("Macro prompt (first 1500 chars):")
        print(build_macro_prompt(data)[:1500], flush=True)
        return

    api_key_openai = os.environ.get("OPENAI_API_KEY")
    if not api_key_openai:
        log("Set OPENAI_API_KEY in .env.local")
        return
    if not httpx:
        log("Install httpx")
        return

    run_ts = time.strftime("%Y%m%d_%H%M")
    suffix = (args.suffix or "").strip() or None
    if suffix:
        log(f"Output suffix: {suffix} (writing to ai_forecast_*_{suffix}.json only)")
    log(f"Run timestamp: {run_ts} (outputs will also be saved with this timestamp)")

    macro_path = os.path.join(DATA_ABS, f"ai_forecast_macro_{suffix}.json") if suffix else os.path.join(DATA_ABS, "ai_forecast_macro.json")
    macro_path_ts = os.path.join(DATA_ABS, f"ai_forecast_macro_{suffix}_{run_ts}.json") if suffix else os.path.join(DATA_ABS, f"ai_forecast_macro_{run_ts}.json")
    by_model_json = os.path.join(DATA_ABS, f"ai_forecast_outlook_by_model_{suffix}.json") if suffix else BY_MODEL_JSON
    output_json = os.path.join(DATA_ABS, f"ai_forecast_outlook_{suffix}.json") if suffix else OUTPUT_JSON
    output_ts = os.path.join(DATA_ABS, f"ai_forecast_outlook_{suffix}_{run_ts}.json") if suffix else os.path.join(DATA_ABS, f"ai_forecast_outlook_{run_ts}.json")
    by_model_ts = os.path.join(DATA_ABS, f"ai_forecast_outlook_by_model_{suffix}_{run_ts}.json") if suffix else os.path.join(DATA_ABS, f"ai_forecast_outlook_by_model_{run_ts}.json")

    def get_key(m):
        return api_key_openai if m.startswith("gpt-") else None

    macro_results = {}
    client = httpx.Client()
    try:
        for model in models_to_run:
            log(f"Macro step: {model} ...")
            try:
                key = get_key(model)
                if not key:
                    log(f"  {model}: skip (no API key)")
                    continue
                out = call_macro(client, key, model, data)
                macro_results[model] = out
                log(f"  {model}: 2035 total={out.get('total_employment_2035_ai_adjusted')}, decline_pp={out.get('total_decline_vs_official_pct')}")
            except Exception as e:
                log(f"  {model} error: {e}")
            time.sleep(args.delay)

        os.makedirs(DATA_ABS, exist_ok=True)
        with open(macro_path, "w", encoding="utf-8") as f:
            json.dump(macro_results, f, indent=2, ensure_ascii=False)
        with open(macro_path_ts, "w", encoding="utf-8") as f:
            json.dump(macro_results, f, indent=2, ensure_ascii=False)
        log(f"Wrote {macro_path} and {macro_path_ts}")

        if args.macro_only:
            return

        macro_total = None
        for m in models_to_run:
            if m in macro_results and macro_results[m].get("total_employment_2035_ai_adjusted") is not None:
                macro_total = int(macro_results[m]["total_employment_2035_ai_adjusted"])
                break
        if macro_total is None:
            macro_total = data["macro"]["employment_2035_official"]
            log(f"No macro result; using official total {macro_total:,}")

        OCC_BATCH = 80
        # Single-model mode: load existing by_model, update current model only, write back
        by_model = {}
        if os.path.exists(by_model_json):
            try:
                with open(by_model_json, encoding="utf-8") as f:
                    by_model = json.load(f)
                log(f"Loaded existing by_model: {list(by_model.keys())}")
            except Exception as e:
                log(f"Could not load {by_model_json}: {e}")

        for model in models_to_run:
            log(f"Model {model}: top-down + bottom-up + reconcile ...")
            try:
                key = get_key(model)
                if not key:
                    continue
                td_list = run_topdown_batched(client, key, model, data, macro_total, OCC_BATCH, args.delay, log)
                bu_list = run_bottomup_batched(client, key, model, data, OCC_BATCH, args.delay, log)
                log(f"    reconcile ...")
                final_list = run_reconcile(client, key, model, macro_total, td_list, bu_list, data, args.delay)
                if final_list:
                    by_model[model] = final_list
                    with open(by_model_json, "w", encoding="utf-8") as f:
                        json.dump(by_model, f, indent=2, ensure_ascii=False)
                    with open(by_model_ts, "w", encoding="utf-8") as f:
                        json.dump(by_model, f, indent=2, ensure_ascii=False)
                    log(f"  {model}: {len(final_list)} occupations, saved to {by_model_json} and {by_model_ts}")
            except Exception as e:
                log(f"  {model} failed: {e}")
            time.sleep(args.delay)

        merged = merge_median(by_model, data["occupations"])
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        with open(output_ts, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        log(f"Wrote {output_json} and {output_ts} ({len(merged)} occupations, from {list(by_model.keys())}). Next: merge_real_data.py -> make_csv_au.py -> build_site_data_au.py")
    finally:
        client.close()


def occ_compact(o):
    """One line per occupation for prompts."""
    return f"{o['anzsco_code']} | {o['title'][:40]} | jobs={o.get('jobs') or 0} | o35={o.get('outlook_2035')} | o25={o.get('outlook_2025_actual')} | us={o.get('us_projection_pct')} | ai_exp={o.get('ai_exposure')}"


def run_topdown_batched(client, api_key, model, data, macro_total, batch_size, delay, log_fn=None):
    """Top-down: per-occupation growth that sums to macro_total. Batched."""
    occs = data["occupations"]
    out = []
    n_batches = (len(occs) + batch_size - 1) // batch_size
    for b, i in enumerate(range(0, len(occs), batch_size)):
        if log_fn:
            log_fn(f"    td batch {b + 1}/{n_batches}")
        batch = occs[i : i + batch_size]
        total_jobs_batch = sum(o.get("jobs") or 0 for o in batch)
        prompt = f"""You are a labour market analyst for Australia. We have a TARGET total employment in 2035: {macro_total:,}.
{LOCAL_VS_GLOBAL_WEIGHTING}
For the following batch, assign a 10-year growth rate (percent, e.g. 5 or -2) to each occupation so the weighted sum is consistent with that total. Classify each as Type A, B, or C and weight o35, o25, us, ai_exp accordingly. You must create both gainers and losers: if some occupations gain, others must stagnate or decline. Return ONLY a JSON array: [ {{ "anzsco_code": "...", "adjusted_growth_pct_2035": <number> }}, ... ] in the same order.

Batch (total jobs in batch: {total_jobs_batch:,}):
"""
        prompt += "\n".join(occ_compact(o) for o in batch)
        resp = _call(client, api_key, model, prompt)
        if resp and isinstance(resp, list):
            out.extend(resp)
        time.sleep(delay)
    return out


def run_bottomup_batched(client, api_key, model, data, batch_size, delay, log_fn=None):
    """Bottom-up: independent per-occupation prediction. Batched."""
    occs = data["occupations"]
    out = []
    n_batches = (len(occs) + batch_size - 1) // batch_size
    for b, i in enumerate(range(0, len(occs), batch_size)):
        if log_fn:
            log_fn(f"    bu batch {b + 1}/{n_batches}")
        batch = occs[i : i + batch_size]
        prompt = f"""You are a labour market analyst for Australia.
{LOCAL_VS_GLOBAL_WEIGHTING}
For each occupation below, give your 10-year employment growth forecast (percent, e.g. 5 or -2) by 2035. Classify each as Type A, B, or C and weight o35, o25, us, ai_exp accordingly. Create both labour gainers and labour losers; routine/compressible (Type C) roles default to negative unless strong local demand outweighs AI substitution. Return ONLY a JSON array: [ {{ "anzsco_code": "...", "adjusted_growth_pct_2035": <number> }}, ... ] in the same order.

Occupations:
"""
        prompt += "\n".join(occ_compact(o) for o in batch)
        resp = _call(client, api_key, model, prompt)
        if resp and isinstance(resp, list):
            out.extend(resp)
        time.sleep(delay)
    return out


def run_reconcile(client, api_key, model, macro_total, td_list, bu_list, data, delay):
    """Reconcile top-down and bottom-up into one final list."""
    by_code_td = {x["anzsco_code"]: x.get("adjusted_growth_pct_2035") for x in td_list if x.get("anzsco_code")}
    by_code_bu = {x["anzsco_code"]: x.get("adjusted_growth_pct_2035") for x in bu_list if x.get("anzsco_code")}
    td_sum = sum(
        (o.get("jobs") or 0) * (1 + (by_code_td.get(o["anzsco_code"]) or 0) / 100)
        for o in data["occupations"]
    )
    bu_sum = sum(
        (o.get("jobs") or 0) * (1 + (by_code_bu.get(o["anzsco_code"]) or 0) / 100)
        for o in data["occupations"]
    )
    n_occ = len(data["occupations"])
    prompt = f"""Produce a final adjusted 2035 occupation outlook under a constrained labour market.

You are not averaging two views. You are allocating a limited future labour pool across occupations. If some occupations gain strongly, others must stagnate or decline.

Two inputs:
1) Top-down (constrained to total {macro_total:,}): {len(by_code_td)} occupations.
2) Bottom-up (independent): implied sum ~{bu_sum:,.0f}.

You MUST:
1. Respect the lower AI-adjusted macro total ({macro_total:,}).
2. Allocate labour demand across occupations, not evaluate each independently.
3. Explicitly create both labour winners and labour losers.
4. Avoid overly broad positive growth; strong positive growth should be concentrated in a smaller set of occupations.
5. Explicitly create a clear negative group (labour losers) and a clear positive group (labour gainers); the outcome should look like reallocation, not broadly positive growth.
6. High-AI-exposure routine occupations (receptionists, clerks, admin support, bookkeepers, call centre, etc.) cannot all remain positive; stress-test them for decline.
7. Classify each occupation into allocation_bucket: "gaining" | "neutral" | "losing".

**Apply Type A / B / C (required — do not ignore):** You must weight signals by occupation type. Do NOT default to Australian official (o35) or recent (o25) for every occupation.
- **Type A (local/policy):** Education, health, aged care, social workers, government. Prioritise o35, o25; use us only as weak reference. These may track AU outlook.
- **Type B (global/market):** Software, product, marketing, design, finance, business ops. **Prioritise us (US projection) as lead indicator;** discount o35 when inconsistent with us and ai_exp. If us is weak and ai_exp high, bias negative.
- **Type C (routine/compressible):** Receptionists, clerks, payroll, bookkeepers, admin support, call centre. **Default bias NEGATIVE** unless local demand clearly offsets AI; do not follow o35 upward for these.

Routine, repetitive, administrative, clerical, basic support, and low-complexity sales roles are default candidates for labour loss. The level and sign of adjusted_growth_pct_2035 must follow from Type A/B/C and allocation logic, not from copying o35.

**Zero growth (core):** Zero growth (exactly 0) should NOT be used as a default fallback. Only assign 0 when there is clear and specific evidence that the occupation's demand will remain structurally unchanged. If the direction is uncertain, you must still make a directional call: use small positive values (e.g. 1–2%) if slight growth is more plausible, or small negative values (e.g. -1 to -2%) if slight decline is more plausible. Avoid using 0 as a proxy for uncertainty. The number of occupations with exactly 0 growth must be limited and should not exceed 10. Zero-growth outcomes should appear only when the evidence genuinely supports a near-flat outlook. Prefer a smoother spread of modest positive, modest negative, and stable outcomes rather than collapsing many occupations to the same neutral value. The final distribution should look organically differentiated, with zero growth used sparingly.

The final distribution should look like a genuine re-sorting of labour demand, not a lightly adjusted version of official projections.

Return ONLY a JSON array for ALL {n_occ} occupations in order of anzsco_code below. Each object: {{ "anzsco_code": "...", "adjusted_growth_pct_2035": <integer>, "allocation_bucket": "gaining"|"neutral"|"losing" }}.

Occupation list below shows o35=AU official 2035, o25=recent 2025, us=US projection, ai_exp=AI exposure. Apply Type A/B/C to each row: do not default to o35; for Type B weight us, for Type C default negative. Use these to make directional calls instead of 0 when uncertain.
"""
    prompt += "\n".join(occ_compact(o) for o in data["occupations"])
    resp = _call(client, api_key, model, prompt)
    if resp and isinstance(resp, list):
        # Ensure allocation_bucket present; derive from growth if missing
        for item in resp:
            if "allocation_bucket" not in item or item.get("allocation_bucket") not in ("gaining", "neutral", "losing"):
                try:
                    g = int(item.get("adjusted_growth_pct_2035", 0))
                    item["allocation_bucket"] = "losing" if g < 0 else ("neutral" if g <= 3 else "gaining")
                except (TypeError, ValueError):
                    item["allocation_bucket"] = "neutral"
        return resp
    # Fallback: use top-down or bottom-up; add allocation_bucket from growth
    fallback = td_list if td_list else bu_list
    for item in fallback:
        if "allocation_bucket" not in item or item.get("allocation_bucket") not in ("gaining", "neutral", "losing"):
            item["allocation_bucket"] = _bucket_from_growth(item.get("adjusted_growth_pct_2035"))
    return fallback


def _call(client, api_key, model, prompt):
    url, headers, model_id = _api_url_headers_model(model, api_key)
    resp = client.post(
        url,
        headers=headers,
        json={"model": model_id, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2},
        timeout=180,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = re.sub(r"^```\w*\n?", "", content)
        content = re.sub(r"\n?```\s*$", "", content)
    return json.loads(content)


def _bucket_from_growth(growth_pct):
    """Derive allocation_bucket from growth: losing | neutral | gaining."""
    if growth_pct is None:
        return "neutral"
    try:
        g = int(growth_pct)
        return "losing" if g < 0 else ("neutral" if g <= 3 else "gaining")
    except (TypeError, ValueError):
        return "neutral"


def merge_median(all_final, occupations):
    """Merge per-model lists: median of adjusted_growth_pct_2035 per anzsco_code. Output list for ai_forecast_outlook.json. Includes allocation_bucket derived from median growth."""
    by_code = {}
    for code in [o["anzsco_code"] for o in occupations]:
        by_code[code] = []
    for model, lst in all_final.items():
        for item in lst:
            c = item.get("anzsco_code")
            pct = item.get("adjusted_growth_pct_2035")
            if c and pct is not None:
                try:
                    by_code.setdefault(c, []).append(float(pct))
                except (TypeError, ValueError):
                    pass
    out = []
    for o in occupations:
        code = o["anzsco_code"]
        vals = by_code.get(code) or []
        if vals:
            vals.sort()
            mid = vals[len(vals) // 2]
            growth = round(mid)
            out.append({
                "anzsco_code": code,
                "adjusted_growth_pct_2035": growth,
                "allocation_bucket": _bucket_from_growth(growth),
            })
        else:
            growth = o.get("outlook_2035") or 0
            out.append({
                "anzsco_code": code,
                "adjusted_growth_pct_2035": growth,
                "allocation_bucket": _bucket_from_growth(growth),
            })
    return out


if __name__ == "__main__":
    main()
