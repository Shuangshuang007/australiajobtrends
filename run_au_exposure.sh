#!/usr/bin/env bash
# Australia AI Exposure one-shot: build pages_au -> score -> refresh site
# Run from Job Outlook Australia folder: ./run_au_exposure.sh
# Set OPENAI_API_KEY (or OPENROUTER_API_KEY) in .env.local or .env

set -e
cd "$(dirname "$0")"

# Load .env / .env.local (current dir and parent hera_one/.env.local)
if [ -f .env ]; then set -a; source .env; set +a; fi
if [ -f .env.local ]; then set -a; source .env.local; set +a; fi
if [ -f ../.env.local ]; then set -a; source ../.env.local; set +a; fi

echo "=== 1/3 Build pages_au (JDS -> Markdown) ==="
python3 scripts/build_pages_au.py

if [ -z "$OPENAI_API_KEY" ] && [ -z "$GEMINI_API_KEY" ] && [ -z "$GOOGLE_API_KEY" ] && [ -z "$OPENROUTER_API_KEY" ]; then
  echo "No OPENAI_API_KEY / GEMINI_API_KEY / OPENROUTER_API_KEY found; skipping scoring."
  echo "Set in .env.local or ../.env.local and re-run to score."
  echo "=== Refreshing site data only (no new exposure) ==="
  python3 build_site_data_au.py
  exit 0
fi

echo "Using: $([ -n "$OPENAI_API_KEY" ] && echo 'OpenAI') $([ -n "$GEMINI_API_KEY$GOOGLE_API_KEY" ] && echo 'Gemini') $([ -n "$OPENROUTER_API_KEY" ] && echo 'OpenRouter')"

echo "=== 2/3 Run scoring (score_au.py) ==="
python3 score_au.py

echo "=== 3/3 Refresh site/data.json ==="
python3 build_site_data_au.py

echo "Done. Start site to view (e.g. python3 -m http.server 5001 --directory site)"
