"""
Use an LLM to impute missing outlook_pct, entry_education (and optionally pay) for grey areas.

Reads occupations_combined.csv + pages_au/*.md. For each occupation with a missing field,
calls the same API as score_au.py with the prompts in IMPUTE_GREY_AREAS.md. Writes
data_abs/imputed.json. Run merge_real_data.py after this (it will apply imputed values
where real data is still empty).

Usage (from Job Outlook Australia):
  python scripts/impute_missing_with_llm.py
  python scripts/impute_missing_with_llm.py --outlook-only
  python scripts/impute_missing_with_llm.py --education-only
  python scripts/impute_missing_with_llm.py --start 0 --end 20

Requires: OPENAI_API_KEY, GEMINI_API_KEY, or OPENROUTER_API_KEY in .env.local / .env.
"""

import argparse
import csv
import json
import os
import re
import time
import httpx
from dotenv import load_dotenv

load_dotenv()
load_dotenv(".env.local")
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env.local"))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
DATA_ABS = os.path.join(BASE_DIR, "data_abs")
COMBINED_CSV = os.path.join(DATA_ABS, "occupations_combined.csv")
PAGES_AU = os.path.join(BASE_DIR, "pages_au")
IMPUTED_JSON = os.path.join(DATA_ABS, "imputed.json")

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
DEFAULT_MODEL_OPENAI = "gpt-4o-mini"
DEFAULT_MODEL_OPENROUTER = "google/gemini-3-flash-preview"
DEFAULT_MODEL_GEMINI = "gemini-3-flash-preview"

EDU_CHOICES = [
    "Bachelor degree or higher",
    "Diploma or Advanced Diploma",
    "Certificate III or IV",
    "Certificate II or III",
    "Certificate I or no formal qualification",
]

PROMPT_OUTLOOK = """You are an expert labour market analyst for Australia. Given an occupation's title and a short description (and optionally its main tasks), estimate the likely **percentage change in employment** for that occupation over the next 5–10 years in Australia. Consider: sector growth, automation risk, ageing population, skills demand, and policy. Use typical official ranges: strong decline about -10% to -5%, slight decline -5% to 0%, little change about 0% to 3%, moderate growth 3% to 8%, strong growth 8% to 15% or more. Respond with ONLY a JSON object, no other text:
{
  "outlook_pct": <integer, e.g. -5 or 7>,
  "rationale": "<1-2 sentences>"
}"""

PROMPT_EDUCATION = """You are an expert in Australian qualifications (AQF). Given an occupation's title and description, choose the **most typical entry-level education** for that occupation in Australia. Use exactly one of these labels:
- "Bachelor degree or higher"
- "Diploma or Advanced Diploma"
- "Certificate III or IV"
- "Certificate II or III"
- "Certificate I or no formal qualification"

Respond with ONLY a JSON object, no other text:
{
  "entry_education": "<exactly one of the five labels above>",
  "rationale": "<1 sentence>"
}"""

PROMPT_PAY = """You are an expert in Australian labour market. Given an occupation's title and description, estimate the **typical median full-time annual earnings in AUD** for that occupation in Australia (rough order of magnitude: e.g. 50000, 80000, 120000). Do not invent precise numbers; round to the nearest 5000–10000. Respond with ONLY a JSON object:
{
  "median_pay_annual": <integer, AUD>,
  "rationale": "<1 sentence>"
}"""


def slugify(title: str) -> str:
    s = re.sub(r"[^\w\s-]", "", title.lower())
    s = re.sub(r"[-\s]+", "-", s).strip("-")
    return s or "occupation"


def norm_code(s) -> str:
    if s is None:
        return ""
    digits = re.sub(r"\D", "", str(s))
    return digits[:4] if len(digits) >= 4 else digits or ""


def call_llm(client, user_text, system_prompt, model, api_url, api_key, use_gemini_query=False):
    url = f"{api_url}?key={api_key}" if use_gemini_query else api_url
    headers = {} if use_gemini_query else {"Authorization": f"Bearer {api_key}"}
    r = client.post(
        url,
        headers=headers,
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.2,
        },
        timeout=60,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
    return json.loads(content)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    ap.add_argument("--outlook-only", action="store_true")
    ap.add_argument("--education-only", action="store_true")
    ap.add_argument("--pay-only", action="store_true")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=None)
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--force", action="store_true", help="Re-impute even if already in imputed.json")
    args = ap.parse_args()

    do_outlook = not args.education_only and not args.pay_only
    do_education = not args.outlook_only and not args.pay_only
    do_pay = args.pay_only
    if args.outlook_only:
        do_education = False
        do_pay = False
    if args.education_only:
        do_outlook = False
        do_pay = False
    if args.pay_only:
        do_outlook = False
        do_education = False

    api_key = (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
    )
    if not api_key:
        print("Set OPENAI_API_KEY, GEMINI_API_KEY, or OPENROUTER_API_KEY in .env.local or .env")
        return

    if os.environ.get("OPENAI_API_KEY"):
        api_url = OPENAI_API_URL
        default_model = DEFAULT_MODEL_OPENAI
        use_gemini_query = False
    elif os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        api_url = GEMINI_API_URL
        default_model = DEFAULT_MODEL_GEMINI
        use_gemini_query = True
    else:
        api_url = OPENROUTER_API_URL
        default_model = DEFAULT_MODEL_OPENROUTER
        use_gemini_query = False

    model = args.model or default_model

    if not os.path.exists(COMBINED_CSV):
        print("Run build_occupations_from_anzsco.py and merge_real_data.py first.")
        return

    rows = []
    with open(COMBINED_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            code = norm_code(row.get("anzsco_code", ""))
            if len(code) != 4:
                continue
            title = (row.get("title") or "").strip()
            if not title:
                continue
            slug = slugify(title)
            outlook = (row.get("outlook_pct") or "").strip()
            education = (row.get("entry_education") or "").strip()
            pay = (row.get("median_pay_annual") or "").strip()
            rows.append({
                "anzsco_code": code,
                "title": title,
                "slug": slug,
                "need_outlook": do_outlook and not outlook,
                "need_education": do_education and not education,
                "need_pay": do_pay and not pay,
            })

    subset = rows[args.start:args.end]
    need_ol = sum(1 for r in subset if r["need_outlook"])
    need_ed = sum(1 for r in subset if r["need_education"])
    need_py = sum(1 for r in subset if r["need_pay"])
    print(f"Subset: {len(subset)} occupations (need outlook: {need_ol}, education: {need_ed}, pay: {need_py})", flush=True)
    print(f"Model: {model}", flush=True)

    imputed = {"outlook": {}, "education": {}, "pay": {}}
    if os.path.exists(IMPUTED_JSON) and not args.force:
        with open(IMPUTED_JSON, encoding="utf-8") as f:
            imputed = json.load(f)
        print(f"Loaded existing imputed.json (outlook: {len(imputed.get('outlook', {}))}, education: {len(imputed.get('education', {}))})", flush=True)

    client = httpx.Client()
    n_outlook = n_edu = n_pay = 0

    for i, r in enumerate(subset):
        slug = r["slug"]
        md_path = os.path.join(PAGES_AU, f"{slug}.md")
        if not os.path.exists(md_path):
            print(f"  [{i+1}/{len(subset)}] {slug} SKIP (no pages_au)", flush=True)
            continue
        with open(md_path, encoding="utf-8") as f:
            user_text = f.read()

        doing = []
        if r["need_outlook"] and slug not in imputed.get("outlook", {}):
            doing.append("outlook")
        if r["need_education"] and slug not in imputed.get("education", {}):
            doing.append("education")
        if r["need_pay"] and slug not in imputed.get("pay", {}):
            doing.append("pay")
        if not doing:
            print(f"  [{i+1}/{len(subset)}] {slug} skip (has data or cached)", flush=True)
        else:
            print(f"  [{i+1}/{len(subset)}] {slug} impute {doing}...", end=" ", flush=True)

        if r["need_outlook"] and slug not in imputed.get("outlook", {}):
            try:
                out = call_llm(client, user_text, PROMPT_OUTLOOK, model, api_url, api_key, use_gemini_query)
                pct = int(out.get("outlook_pct", 0))
                pct = max(-20, min(25, pct))
                imputed.setdefault("outlook", {})[slug] = {"outlook_pct": pct, "rationale": out.get("rationale", "")}
                n_outlook += 1
                print(f"outlook={pct}%", end=" ", flush=True)
            except Exception as e:
                print(f"outlook ERROR: {e}", flush=True)

        if r["need_education"] and slug not in imputed.get("education", {}):
            try:
                out = call_llm(client, user_text, PROMPT_EDUCATION, model, api_url, api_key, use_gemini_query)
                edu = out.get("entry_education", "").strip()
                if edu not in EDU_CHOICES:
                    for c in EDU_CHOICES:
                        if c.lower() in edu.lower() or edu.lower() in c.lower():
                            edu = c
                            break
                    else:
                        edu = EDU_CHOICES[0]
                imputed.setdefault("education", {})[slug] = {"entry_education": edu, "rationale": out.get("rationale", "")}
                n_edu += 1
                print(f"education={edu[:35]}", end=" ", flush=True)
            except Exception as e:
                print(f"education ERROR: {e}", flush=True)

        if r["need_pay"] and slug not in imputed.get("pay", {}):
            try:
                out = call_llm(client, user_text, PROMPT_PAY, model, api_url, api_key, use_gemini_query)
                pay = int(out.get("median_pay_annual", 60000))
                pay = max(20000, min(300000, pay))
                imputed.setdefault("pay", {})[slug] = {"median_pay_annual": pay, "rationale": out.get("rationale", "")}
                n_pay += 1
                print(f"pay=A${pay:,}", end=" ", flush=True)
            except Exception as e:
                print(f"pay ERROR: {e}", flush=True)

        if doing:
            print("", flush=True)

        with open(IMPUTED_JSON, "w", encoding="utf-8") as f:
            json.dump(imputed, f, indent=2)

        if i < len(subset) - 1:
            time.sleep(args.delay)

    client.close()
    print(f"Done. Imputed: outlook {n_outlook}, education {n_edu}, pay {n_pay}. Wrote {IMPUTED_JSON}", flush=True)
    print("Next: run merge_real_data.py to apply imputed values into occupations_combined.csv.")


if __name__ == "__main__":
    main()
