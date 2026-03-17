"""
Score each Australian occupation's AI exposure using an LLM (OpenAI or OpenRouter).

Reads Markdown from pages_au/ (built by scripts/build_pages_au.py from JSA profiles),
sends each to an LLM with the same rubric as the US (adapted for JSA source).
Results cached incrementally to scores_au.json. build_site_data_au.py merges
these into site/data.json for the exposure layer.

Usage:
  python score_au.py
  python score_au.py --model gpt-4o-mini   # OpenAI
  python score_au.py --start 0 --end 10
  python score_au.py --force   # re-score all

Requires one of: OPENAI_API_KEY, GEMINI_API_KEY (Google AI), or OPENROUTER_API_KEY (in .env.local or .env).
US version uses OpenRouter with model google/gemini-3-flash-preview. With Gemini key we use the same model: gemini-3-flash-preview (Google AI direct).
Loads: .env, .env.local, ../.env.local (hera_one/.env.local). Run build_pages_au.py first.
"""

import argparse
import csv
import json
import os
import time
import httpx
from dotenv import load_dotenv

# Load env: current dir then parent (for hera_one/.env.local)
load_dotenv()
load_dotenv(".env.local")
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env.local"))

OUTPUT_FILE = "scores_au.json"
PAGES_AU = "pages_au"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
# Google AI (Gemini) OpenAI-compatible: https://ai.google.dev/gemini-api/docs/openai
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
DEFAULT_MODEL_OPENAI = "gpt-4o-mini"
# US Job Outlook uses this via OpenRouter; same model for Gemini API direct = gemini-3-flash-preview
DEFAULT_MODEL_OPENROUTER = "google/gemini-3-flash-preview"
DEFAULT_MODEL_GEMINI = "gemini-3-flash-preview"

# Same rubric as US; only the data-source line is changed for Australia (JSA).
SYSTEM_PROMPT = """\
You are an expert analyst evaluating how exposed different occupations are to \
AI. You will be given a short description and list of tasks for an occupation \
from Jobs and Skills Australia (Australian government occupation profiles).

Rate the occupation's overall **AI Exposure** on a scale from 0 to 10.

AI Exposure measures: how much will AI reshape this occupation? Consider both \
direct effects (AI automating tasks currently done by humans) and indirect \
effects (AI making each worker so productive that fewer are needed).

A key signal is whether the job's work product is fundamentally digital. If \
the job can be done entirely from a home office on a computer — writing, \
coding, analyzing, communicating — then AI exposure is inherently high (7+), \
because AI capabilities in digital domains are advancing rapidly. Even if \
today's AI can't handle every aspect of such a job, the trajectory is steep \
and the ceiling is very high. Conversely, jobs requiring physical presence, \
manual skill, or real-time human interaction in the physical world have a \
natural barrier to AI exposure.

Use these anchors to calibrate your score:

- **0–1: Minimal exposure.** The work is almost entirely physical, hands-on, \
or requires real-time human presence in unpredictable environments. AI has \
essentially no impact on daily work. \
Examples: roofer, landscaper, commercial diver.

- **2–3: Low exposure.** Mostly physical or interpersonal work. AI might help \
with minor peripheral tasks (scheduling, paperwork) but doesn't touch the \
core job. \
Examples: electrician, plumber, firefighter, dental hygienist.

- **4–5: Moderate exposure.** A mix of physical/interpersonal work and \
knowledge work. AI can meaningfully assist with the information-processing \
parts but a substantial share of the job still requires human presence. \
Examples: registered nurse, police officer, veterinarian.

- **6–7: High exposure.** Predominantly knowledge work with some need for \
human judgment, relationships, or physical presence. AI tools are already \
useful and workers using AI may be substantially more productive. \
Examples: teacher, manager, accountant, journalist.

- **8–9: Very high exposure.** The job is almost entirely done on a computer. \
All core tasks — writing, coding, analyzing, designing, communicating — are \
in domains where AI is rapidly improving. The occupation faces major \
restructuring. \
Examples: software developer, graphic designer, translator, data analyst, \
paralegal, copywriter.

- **10: Maximum exposure.** Routine information processing, fully digital, \
with no physical component. AI can already do most of it today. \
Examples: data entry clerk, telemarketer.

Respond with ONLY a JSON object in this exact format, no other text:
{
  "exposure": <0-10>,
  "rationale": "<2-3 sentences explaining the key factors>"
}\
"""


def score_occupation(client, text, model, api_url, api_key, use_gemini_key_in_query=False):
    """Send one occupation to the LLM and parse the structured response."""
    if use_gemini_key_in_query:
        url = f"{api_url}?key={api_key}"
        headers = {}
    else:
        url = api_url
        headers = {"Authorization": f"Bearer {api_key}"}
    response = client.post(
        url,
        headers=headers,
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "temperature": 0.2,
        },
        timeout=60,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]

    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    return json.loads(content)


def load_occupations():
    """Load list of {slug, title} from occupations_au.csv (must run make_csv_au.py first)."""
    path = "occupations_au.csv"
    if not os.path.exists(path):
        return None
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            slug = (row.get("slug") or "").strip()
            title = (row.get("title") or "").strip()
            if slug and title:
                rows.append({"slug": slug, "title": title})
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None, help="e.g. gpt-4o-mini (OpenAI) or google/gemini-3-flash-preview (OpenRouter)")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=None)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--force", action="store_true", help="Re-score even if already cached")
    args = parser.parse_args()

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

    occupations = load_occupations()
    if not occupations:
        print("Run make_csv_au.py first to create occupations_au.csv")
        return

    subset = occupations[args.start:args.end]

    scores = {}
    if os.path.exists(OUTPUT_FILE) and not args.force:
        with open(OUTPUT_FILE) as f:
            for entry in json.load(f):
                scores[entry["slug"]] = entry

    print(f"Scoring {len(subset)} occupations with {model}")
    print(f"Already cached: {len(scores)}")

    errors = []
    client = httpx.Client()

    for i, occ in enumerate(subset):
        slug = occ["slug"]

        if slug in scores:
            continue

        md_path = os.path.join(PAGES_AU, f"{slug}.md")
        if not os.path.exists(md_path):
            print(f"  [{i+1}] SKIP {slug} (no markdown; run scripts/build_pages_au.py)")
            continue

        with open(md_path, encoding="utf-8") as f:
            text = f.read()

        print(f"  [{i+1}/{len(subset)}] {occ['title'][:50]}...", end=" ", flush=True)

        try:
            result = score_occupation(client, text, model, api_url, api_key, use_gemini_query)
            scores[slug] = {
                "slug": slug,
                "title": occ["title"],
                **result,
            }
            print(f"exposure={result['exposure']}")
        except Exception as e:
            print(f"ERROR: {e}")
            errors.append(slug)

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(list(scores.values()), f, indent=2)

        if i < len(subset) - 1:
            time.sleep(args.delay)

    client.close()

    print(f"\nDone. Scored {len(scores)} occupations, {len(errors)} errors.")
    if errors:
        print(f"Errors: {errors}")

    vals = [s for s in scores.values() if "exposure" in s]
    if vals:
        avg = sum(s["exposure"] for s in vals) / len(vals)
        by_score = {}
        for s in vals:
            bucket = s["exposure"]
            by_score[bucket] = by_score.get(bucket, 0) + 1
        print(f"\nAverage exposure across {len(vals)} occupations: {avg:.1f}")
        print("Distribution:")
        for k in sorted(by_score):
            print(f"  {k}: {'█' * by_score[k]} ({by_score[k]})")
    print("\nNext: python build_site_data_au.py to refresh site/data.json with exposure.")


if __name__ == "__main__":
    main()
