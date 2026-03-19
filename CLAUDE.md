# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Agent

```bash
# With niche as argument
python main.py "AI agent SaaS startups"

# Interactive mode
python main.py

# Install dependencies
pip install -r requirements.txt
pip install ddgs  # replaces duckduckgo_search (renamed package)
```

## Environment Variables

Copy `.env.example` → `.env` and set:
- `GEMINI_API_KEY` — Primary LLM (gemini-2.0-flash, 1500 req/day free). Get from aistudio.google.com
- `GROQ_API_KEY` — Fallback LLM (llama-3.3-70b-versatile, 100k tokens/day free). Get from console.groq.com
- `GITHUB_TOKEN` — Optional (boosts GitHub rate limit 60→5000/hr)
- `GOOGLE_MAPS_API_KEY` — Optional (enables Maps search)

The agent tries Gemini first, automatically falls back to Groq on quota exhaustion.

## Architecture

**Dual-backend agentic tool loop** (`agent.py`): `find_leads()` tries `_find_leads_gemini()` first, falls back to `_find_leads_groq()` on `429 RESOURCE_EXHAUSTED`. Both backends run the same tool loop — call tools autonomously, receive results, loop until a final JSON array of leads is emitted. Max 25 turns.

**Groq quirk**: Llama 3.3 on Groq randomly emits XML-style function calls (`<function=name={"args"}>`) instead of proper JSON tool_calls. `_parse_xml_tool_call()` recovers these with a regex fallback and injects synthetic message pairs to keep conversation history consistent.

**Tools** (4 active):
- `search_google` — DuckDuckGo via `ddgs` package (renamed from `duckduckgo_search`), retries once on rate limit
- `search_github` — GitHub REST API; parallelizes user-detail calls with `ThreadPoolExecutor(max_workers=5)`
- `search_google_maps` — Google Places API; parallelizes Place Details calls; gracefully skips if key missing
- `fetch_webpage` — `httpx` + `html2text`; auto-discovers 16 contact page patterns (`/contact`, `/about`, `/team`, etc.); fetches top 3 in parallel; extracts emails, LinkedIn, phones, social; has SSRF guard

**Data flow**: `main.py` → `agent.find_leads(niche)` → tool loop → JSON parse → `list[Lead]` → `display.display_leads()` + `save_leads_csv()`

**Output**: Rich CLI table + CSV file `leads_<niche>_<date>.csv` (appends on repeat runs same day).

**`Lead` dataclass** (`models.py`): `company_name`, `source`, `description`, `url`, `website`, `email`, `linkedin`, `why_good_lead`, `score` (1–10).

## Key Implementation Details

**Gemini tool format**: Uses `google-genai` SDK (`google.genai`). Tools defined as `types.Tool(function_declarations=[...])`. History built as `list[types.Content]`; tool results sent as `types.Part(function_response=...)`.

**Groq tool format**: OpenAI-compatible. Tools defined as `{"type": "function", "function": {...}}`. Messages rebuilt as plain dicts (not Pydantic objects) to avoid serialization issues across turns.

**JSON parsing**: `_parse_leads_from_text()` strips markdown fences then uses `re.search(r'\[.*\]', text, re.DOTALL)` to find the array even with stray text around it.

**`search_google`** imports from `ddgs` with fallback to `duckduckgo_search` for backwards compatibility.

## Skills & Subagents

`.claude/skills/` contains two reusable skills:
- `gmaps-leads` — full Google Maps → website enrichment → Google Sheets pipeline (needs `APIFY_API_TOKEN`)
- `classify-leads` — post-process leads with Anthropic Batches API for fast parallel classification

`.claude/agents/` contains subagents for code review, QA, research, and email classification. Design workflow: spawn `code-reviewer` + `qa` in parallel after non-trivial code changes; parent agent applies all fixes.

## Adding a New Search Source

1. Add a function in `tools/<name>.py` returning `list[dict]`
2. Export it from `tools/__init__.py`
3. Add a `FunctionDeclaration` to `TOOLS` in `agent.py` (Gemini format) and a matching entry in `_find_leads_groq()` (OpenAI format)
4. Add a dispatch branch in `dispatch_tool()`
5. Update the system prompt strategy section
