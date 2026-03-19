# Leads Agent

An agentic lead generation tool that autonomously searches the web, GitHub, and Google Maps to find qualified B2B leads for any niche. Uses a dual-LLM backend (Gemini + Groq fallback) with a tool-calling loop.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and fill in your API keys
cp .env.example .env

# Run with a niche
python main.py "AI agent SaaS startups"

# Or run interactively
python main.py
```

Output is saved to `output/leads_<niche>_<date>.csv`.

## Setup

### Required

At least one LLM key:
- **Gemini** (recommended): free at [aistudio.google.com](https://aistudio.google.com) — 1500 req/day
- **Groq** (fallback): free at [console.groq.com](https://console.groq.com) — 100k tokens/day

### Optional

| Variable | Purpose |
|---|---|
| `GITHUB_TOKEN` | Boosts GitHub rate limit from 60 → 5000 req/hr |
| `GOOGLE_MAPS_API_KEY` | Enables Google Maps local business search |

## How It Works

The agent runs a tool loop (max 25 turns) calling four tools autonomously:

| Tool | Description |
|---|---|
| `search_google` | DuckDuckGo web search via `ddgs` |
| `search_github` | GitHub REST API — finds repos, orgs, users |
| `search_google_maps` | Google Places API — finds local businesses |
| `fetch_webpage` | Fetches websites, extracts emails, LinkedIn, phones |

Results are deduplicated, scored 1–10, and returned as a structured list of leads.

## Output

Each lead includes:
- `company_name`, `website`, `email`, `linkedin`
- `source` (google / github / maps)
- `description`, `why_good_lead`
- `score` (1–10)

Displayed as a Rich CLI table and saved to `output/`.

## Architecture

```
main.py          → entry point, CSV saving
agent.py         → dual-backend tool loop (Gemini + Groq)
models.py        → Lead dataclass
display.py       → Rich CLI table
tools/           → search_google, search_github, search_google_maps, fetch_webpage
output/          → generated CSVs (gitignored)
```

The agent tries Gemini first and automatically falls back to Groq on quota exhaustion (`429 RESOURCE_EXHAUSTED`).

## Skills & Subagents

`.claude/skills/` contains reusable Claude Code skills:
- `gmaps-leads` — Google Maps → website enrichment pipeline
- `classify-leads` — LLM-based lead classification via Anthropic Batches API

`.claude/agents/` contains subagents for code review, QA, research, and email classification.
