# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt
pip install ddgs  # replaces duckduckgo_search (renamed package)

# Generate leads (with niche as argument or interactive)
python main.py "AI agent SaaS startups"
python main.py

# Filter an existing CSV
python main.py filter output/leads_gym_owners_2026-03-20.csv --score 5 --has-email --type local_service --location sydney

# Full pipeline: generate → filter → (optionally) hand off to outreach agent
python main.py pipeline "gym owners sydney" --score 5 --has-email --outreach
```

Filter flags (work on both `filter` and `pipeline` subcommands): `--score N`, `--has-email`, `--has-website`, `--type {saas|agency|local_service|ecommerce|other}`, `--location TEXT`, `--outreach`.

## Environment Variables

Copy `.env.example` → `.env` and set:
- `GEMINI_API_KEY` — Primary LLM (gemini-2.0-flash, 1500 req/day free). Get from aistudio.google.com
- `GROQ_API_KEY` — Fallback LLM (llama-3.3-70b-versatile, 100k tokens/day free). Get from console.groq.com
- `GITHUB_TOKEN` — Optional (boosts GitHub rate limit 60→5000/hr)
- `GOOGLE_MAPS_API_KEY` — Optional (enables Maps search)

## Architecture

### LLM Backend Chain

`find_leads()` in `agent.py` tries backends in order: **Gemini → Groq → OpenRouter → Ollama (local)**. Each backend runs the same agentic tool loop — call tools autonomously, receive results, loop until a final JSON array of leads is emitted. Max 25 turns.

- **Gemini**: Uses `google-genai` SDK. Tools as `types.Tool(function_declarations=[...])`. History as `list[types.Content]`.
- **Groq**: OpenAI-compatible client. Messages rebuilt as plain dicts (not Pydantic) to avoid serialization issues. Auto-switches between 4 Llama models on rate limits.
- **OpenRouter**: OpenAI-compatible. Tries 4 free models in sequence.
- **Ollama**: Local fallback, no API key needed. Auto-detects available models.

**Groq quirk**: Llama 3.3 randomly emits XML-style function calls (`<function=name={"args"}>`) instead of proper tool_calls. `_parse_xml_tool_call()` recovers these with regex and injects synthetic message pairs to keep conversation history consistent. This also happens with Ollama small models.

### Data Flow

```
main.py → agent.find_leads(niche) → tool loop → JSON parse → list[Lead]
  ├─ display.display_leads() → Rich CLI table
  ├─ save_leads_csv() → output/leads_<niche>_<date>.csv
  │
  ├─ filter.filter_leads() → list[FilteredLead]  (if filter/pipeline subcommand)
  │   ├─ extract_location() — TLD mapping + city/country scan in description
  │   ├─ classify_business_type() — keyword heuristics
  │   └─ compute_priority_score() — weighted 0-100 composite
  ├─ filter_display.display_filtered_leads() → Rich CLI table
  ├─ save_filtered_csv() → output/filtered_leads_<niche>_<date>.csv
  │
  └─ launch_outreach() → subprocess to /Users/nishit/Desktop/outreach-agent/main.py  (if --outreach)
```

### Priority Scoring (filter.py)

Weighted 0-100 composite: has email (+30), has website (+20), agent score (up to +25), business type match (+15), location match (+10).

### Tools (4 active, dispatched via `dispatch_tool()` in agent.py)

| Tool | Source | Notes |
|------|--------|-------|
| `search_google` | DuckDuckGo via `ddgs` | Retries once on rate limit. Import: `ddgs` with fallback to `duckduckgo_search` |
| `search_github` | GitHub REST API | Parallelizes user-detail calls (ThreadPoolExecutor, max_workers=5) |
| `search_google_maps` | Google Places API | Parallelized Place Details; gracefully skips if key missing |
| `fetch_webpage` | httpx + html2text | Auto-discovers 16 contact page patterns; fetches top 3 in parallel; SSRF guard blocks private IPs |

Tools registered in `tools/__init__.py` must also be declared in **3 places** in `agent.py`: Gemini `TOOLS` list, each Groq/OpenRouter/Ollama backend's tool list, and `dispatch_tool()`.

### Models

- `Lead` (`models.py`): `company_name`, `source`, `description`, `url`, `website`, `email`, `linkedin`, `why_good_lead`, `score` (1–10).
- `FilteredLead` (`models.py`): All Lead fields + `priority_score` (0-100), `business_type`, `location`, `has_email`, `has_website`.

### Outreach Agent Integration

Filtered CSVs are directly compatible with `/Users/nishit/Desktop/outreach-agent/main.py`. The outreach agent reads via `csv.DictReader` and uses: `company_name`, `website`, `email`, `description`, `score`, `linkedin`, `why_good_lead`. Extra columns (`priority_score`, `business_type`) are silently ignored.

## Adding a New Search Source

1. Add a function in `tools/<name>.py` returning `list[dict]`
2. Export it from `tools/__init__.py`
3. Add a `FunctionDeclaration` to `TOOLS` in `agent.py` (Gemini format) **and** matching entries in each backend's tool list (`_find_leads_groq`, `_find_leads_openrouter`, `_find_leads_ollama`)
4. Add a dispatch branch in `dispatch_tool()`
5. Update the system prompt strategy section

## Skills & Subagents

`.claude/skills/` contains two reusable skills:
- `gmaps-leads` — Google Maps → website enrichment → Google Sheets pipeline (needs `APIFY_API_TOKEN`)
- `classify-leads` — post-process leads with Anthropic Batches API for parallel classification

`.claude/agents/` contains subagents for code review, QA, research, and email classification. Workflow: spawn `code-reviewer` + `qa` in parallel after non-trivial changes; parent agent applies all fixes.
