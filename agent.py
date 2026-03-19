import json
import os
import re
import uuid
from google import genai
from google.genai import types
from google.genai.errors import ClientError
from groq import Groq, BadRequestError as GroqBadRequestError
from openai import OpenAI
from tools import (
    search_google,
    search_github,
    search_google_maps,
    fetch_webpage,
)
from models import Lead

# Gemini function declarations (native format)
TOOLS = [
    types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="search_google",
            description=(
                "Search the web using DuckDuckGo. Run 3 searches with different queries: "
                "'[niche] companies', '[niche] SaaS startups', '[niche] software tools B2B'. "
                "Returns titles, URLs, and snippets."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "query": types.Schema(type="STRING", description="Search query string"),
                    "max_results": types.Schema(type="INTEGER", description="Max results (1-15)"),
                },
                required=["query"],
            ),
        ),
        types.FunctionDeclaration(
            name="search_github",
            description=(
                "Search GitHub for companies building in the niche. "
                "Use search_type='repositories' for active codebases, 'users' for company org accounts."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "query": types.Schema(type="STRING", description="Search query string"),
                    "search_type": types.Schema(
                        type="STRING",
                        description="'repositories' or 'users'",
                        enum=["repositories", "users"],
                    ),
                    "max_results": types.Schema(type="INTEGER", description="Max results (1-15)"),
                },
                required=["query"],
            ),
        ),
        types.FunctionDeclaration(
            name="search_google_maps",
            description=(
                "Search Google Places for local agencies, consultancies, and businesses in the niche. "
                "Gracefully skips if GOOGLE_MAPS_API_KEY is not set."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "query": types.Schema(type="STRING", description="Search query, e.g. 'AI consulting firms'"),
                    "location": types.Schema(type="STRING", description="Optional location, e.g. 'San Francisco'"),
                    "max_results": types.Schema(type="INTEGER", description="Max results"),
                },
                required=["query"],
            ),
        ),
        types.FunctionDeclaration(
            name="fetch_webpage",
            description=(
                "Fetch a company homepage to extract emails, LinkedIn URLs, and phone numbers. "
                "Auto-discovers /contact and /about sub-pages. "
                "Call this for the top 5 most promising companies found."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "url": types.Schema(type="STRING", description="Company homepage URL"),
                    "company_name": types.Schema(type="STRING", description="Company name (optional)"),
                },
                required=["url"],
            ),
        ),
    ])
]

SYSTEM_PROMPT = """You are an expert B2B lead generation researcher. Find high-quality potential B2B clients in a given niche.

## Research Strategy
Use the tools efficiently:
1. **search_google**: Run 3 searches with varied angles — "[niche] companies", "[niche] SaaS startups", "[niche] software tools B2B"
2. **search_github**: Run 2 searches — search_type=repositories for active builders, search_type=users for company orgs
3. **search_google_maps**: Search for agencies/consultancies in the niche (handles missing API key gracefully)
4. **fetch_webpage**: For the top 5 most promising companies, fetch their homepage to extract emails and LinkedIn

## Contact Enrichment
Call **fetch_webpage** only on the best 5 leads — it's slow but extracts real contact info (emails, LinkedIn, phones).

## Output
After all research, output a JSON array. Each object MUST have ALL these fields:
```json
{
  "company_name": "string",
  "source": "google|producthunt|github|reddit|maps",
  "description": "what they do, 1-2 sentences",
  "url": "direct URL to profile/listing",
  "website": "company homepage or empty string",
  "email": "contact email if found via fetch_webpage, else empty string",
  "linkedin": "LinkedIn URL if found, else empty string",
  "why_good_lead": "specific reason: growth signals, team size, pain points, recent activity",
  "score": 8
}
```

## Scoring (1-10)
- **9-10**: Funded or established company, active product, clear B2B pain point, contact info found (email/LinkedIn)
- **7-8**: Active company with product/team, good growth signals, some contact info
- **5-6**: Legitimate company but limited signals — no contact info, unclear fit, or small scale
- **3-4**: Unclear if company, no website, minimal activity
- **1-2**: Individual developer, hobby project, or clear mismatch

Return ONLY the JSON array — no markdown, no explanation. Aim for 10-20 leads. Companies only, not individuals."""


def dispatch_tool(tool_name: str, tool_input: dict) -> str:
    try:
        if tool_name == "search_google":
            result = search_google(
                query=tool_input["query"],
                max_results=tool_input.get("max_results", 10),
            )
        elif tool_name == "search_github":
            result = search_github(
                query=tool_input["query"],
                search_type=tool_input.get("search_type", "repositories"),
                max_results=tool_input.get("max_results", 10),
            )
        elif tool_name == "search_google_maps":
            result = search_google_maps(
                query=tool_input["query"],
                location=tool_input.get("location", ""),
                max_results=tool_input.get("max_results", 10),
            )
        elif tool_name == "fetch_webpage":
            result = fetch_webpage(
                url=tool_input["url"],
                company_name=tool_input.get("company_name", ""),
            )
        else:
            result = {"error": f"Unknown tool: {tool_name}"}
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


def _parse_xml_tool_call(text: str) -> tuple[str, str, dict] | None:
    """
    Llama models emit various XML-style function calls instead of proper tool_calls.
    Handles multiple formats:
      <function=name={"k":"v"}>  <function=name":{"k":"v"}>
      <function=name [url]{"k":"v"}</function>
      =function=name>{"k":"v"}</function>  (missing leading <)
    Returns (fake_id, tool_name, tool_args) or None (first match only).
    """
    patterns = [
        r'<?=?function=(\w+)[^<{]*?(\{[^<]*?\})\s*(?:</function>|>)',
        r'<function=(\w+)[^<]*?(\{[^<]*\})\s*</function>',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.DOTALL):
            name = match.group(1)
            try:
                args = json.loads(match.group(2))
                return str(uuid.uuid4()), name, args
            except json.JSONDecodeError:
                continue
    return None


def _parse_all_xml_tool_calls(text: str) -> list[tuple[str, str, dict]]:
    """Extract all XML-style function calls from text."""
    results = []
    patterns = [
        r'<?=?function=(\w+)[^<{]*?(\{[^<]*?\})\s*(?:</function>|>)',
        r'<function=(\w+)[^<]*?(\{[^<]*\})\s*</function>',
    ]
    seen = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.DOTALL):
            name = match.group(1)
            raw_args = match.group(2)
            if raw_args in seen:
                continue
            seen.add(raw_args)
            try:
                args = json.loads(raw_args)
                results.append((str(uuid.uuid4()), name, args))
            except json.JSONDecodeError:
                continue
    return results


def _parse_leads_from_text(text: str) -> list[Lead] | None:
    """Extract JSON array from model text, handling markdown fences."""
    text = text.strip()
    # Strip code fences and extract JSON array (handles truncated output too)
    fence_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    else:
        # Remove opening fence if present
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```\s*$', '', text.strip())
        # Find from first '[' to last ']', or just from first '[' if truncated
        bracket_start = text.find('[')
        if bracket_start != -1:
            bracket_end = text.rfind(']')
            if bracket_end > bracket_start:
                text = text[bracket_start:bracket_end + 1]
            else:
                text = text[bracket_start:]  # truncated — repair below
    try:
        leads_data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        # Try to repair truncated JSON by closing open brackets
        repaired = text.rstrip().rstrip(',')
        open_braces = repaired.count('{') - repaired.count('}')
        open_brackets = repaired.count('[') - repaired.count(']')
        repaired += '}' * max(open_braces, 0) + ']' * max(open_brackets, 0)
        try:
            leads_data = json.loads(repaired)
        except (json.JSONDecodeError, ValueError):
            return None
    try:
        if not isinstance(leads_data, list):
            return None
        leads = []
        for item in leads_data:
            leads.append(Lead(
                company_name=item.get("company_name", "Unknown"),
                source=item.get("source", "unknown"),
                description=item.get("description", ""),
                url=item.get("url", ""),
                website=item.get("website", ""),
                email=item.get("email", ""),
                linkedin=item.get("linkedin", ""),
                why_good_lead=item.get("why_good_lead", ""),
                score=int(item.get("score", 5)),
            ))
        return sorted(leads, key=lambda x: x.score, reverse=True)
    except (json.JSONDecodeError, ValueError):
        return None


def _find_leads_groq(niche: str, verbose: bool = False) -> list[Lead]:
    """Groq/Llama backend with XML tool-call fallback recovery."""
    groq_tools = [
        {"type": "function", "function": {
            "name": "search_google",
            "description": "Search the web using DuckDuckGo. Returns titles, URLs, and snippets.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]},
        }},
        {"type": "function", "function": {
            "name": "search_github",
            "description": "Search GitHub repos or org accounts for companies in the niche.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"},
                "search_type": {"type": "string", "enum": ["repositories", "users"]},
                "max_results": {"type": "integer"}}, "required": ["query"]},
        }},
        {"type": "function", "function": {
            "name": "search_google_maps",
            "description": "Search Google Places for agencies/consultancies in the niche.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"}, "location": {"type": "string"},
                "max_results": {"type": "integer"}}, "required": ["query"]},
        }},
        {"type": "function", "function": {
            "name": "fetch_webpage",
            "description": "Fetch a company homepage to extract emails and LinkedIn URLs.",
            "parameters": {"type": "object", "properties": {
                "url": {"type": "string"}, "company_name": {"type": "string"}}, "required": ["url"]},
        }},
    ]
    # Models tried in order; each has its own daily quota on Groq free tier
    groq_models = [
        "llama-3.3-70b-versatile",   # 100k/day
        "llama-3.1-8b-instant",      # 500k/day
        "llama3-70b-8192",           # 100k/day
        "llama3-8b-8192",            # 500k/day
    ]
    groq_model = groq_models[0]
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Find B2B leads in this niche: {niche}"},
    ]
    max_turns = 25
    for turn in range(max_turns):
        try:
            response = client.chat.completions.create(
                model=groq_model,
                max_tokens=8096,
                tools=groq_tools,
                tool_choice="auto",
                parallel_tool_calls=False,
                messages=messages,
            )
        except Exception as e:
            # Switch Groq model on rate limit
            if "429" in str(e) or "rate_limit" in str(e).lower() or "rate limit" in str(e).lower():
                remaining = [gm for gm in groq_models if gm != groq_model]
                if remaining:
                    groq_model = remaining[0]
                    groq_models = remaining
                    if verbose:
                        print(f"  [Groq] Rate limit, switching to {groq_model}...")
                    continue
                raise  # all Groq models exhausted
            if not isinstance(e, GroqBadRequestError):
                raise
            # Skip decommissioned/invalid models
            error_body = e.body if isinstance(e.body, dict) else {}
            err_code = (error_body.get("error") or {}).get("code", "")
            if err_code in ("model_decommissioned", "model_not_found"):
                remaining = [gm for gm in groq_models if gm != groq_model]
                if remaining:
                    groq_model = remaining[0]
                    groq_models = remaining
                    if verbose:
                        print(f"  [Groq] Model unavailable, switching to {groq_model}...")
                    continue
                raise RuntimeError("All Groq models exhausted or unavailable")
            # XML tool-call recovery
            error_body = e.body if isinstance(e.body, dict) else {}
            failed_gen = (error_body.get("error") or {}).get("failed_generation", "")
            if not failed_gen:
                m = re.search(r"'failed_generation': '(.+?)'[,}]", str(e))
                failed_gen = m.group(1) if m else ""
            parsed = _parse_xml_tool_call(failed_gen)
            if not parsed:
                raise RuntimeError(f"Groq unrecoverable error: {e}")
            fake_id, tool_name, tool_args = parsed
            if verbose:
                print(f"  [Tool/fallback] {tool_name}({json.dumps(tool_args)[:120]})")
            result = dispatch_tool(tool_name, tool_args)
            messages.append({"role": "assistant", "content": "", "tool_calls": [
                {"id": fake_id, "type": "function", "function": {"name": tool_name, "arguments": json.dumps(tool_args)}}
            ]})
            messages.append({"role": "tool", "tool_call_id": fake_id, "content": result})
            continue

        msg = response.choices[0].message
        finish_reason = response.choices[0].finish_reason
        assistant_msg: dict = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant_msg["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]
        messages.append(assistant_msg)

        if finish_reason == "stop":
            text = msg.content or ""
            leads = _parse_leads_from_text(text)
            if leads is not None:
                return leads
            # Model may have emitted tool calls as text instead of tool_calls
            inline_calls = _parse_all_xml_tool_calls(text)
            if inline_calls:
                # Remove the assistant message we just added (it has bad content)
                messages.pop()
                tool_results = []
                tc_refs = []
                for fake_id, tool_name, tool_args in inline_calls:
                    if verbose:
                        print(f"  [Tool/inline] {tool_name}({json.dumps(tool_args)[:120]})")
                    result = dispatch_tool(tool_name, tool_args)
                    tc_refs.append({"id": fake_id, "type": "function", "function": {"name": tool_name, "arguments": json.dumps(tool_args)}})
                    tool_results.append({"role": "tool", "tool_call_id": fake_id, "content": result})
                messages.append({"role": "assistant", "content": "", "tool_calls": tc_refs})
                messages.extend(tool_results)
                continue
            print(f"[Groq] JSON parse failed. Raw: {text[:300]}")
            return []
        elif finish_reason == "tool_calls":
            for tc in (msg.tool_calls or []):
                if verbose:
                    print(f"  [Tool] {tc.function.name}({tc.function.arguments[:120]})")
                result = dispatch_tool(tc.function.name, json.loads(tc.function.arguments))
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    return []


def _find_leads_openrouter(niche: str, verbose: bool = False) -> list[Lead]:
    """OpenRouter fallback using free Llama model (OpenAI-compatible)."""
    or_tools = [
        {"type": "function", "function": {
            "name": "search_google",
            "description": "Search the web using DuckDuckGo. Returns titles, URLs, and snippets.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]},
        }},
        {"type": "function", "function": {
            "name": "search_github",
            "description": "Search GitHub repos or org accounts for companies in the niche.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"},
                "search_type": {"type": "string", "enum": ["repositories", "users"]},
                "max_results": {"type": "integer"}}, "required": ["query"]},
        }},
        {"type": "function", "function": {
            "name": "search_google_maps",
            "description": "Search Google Places for agencies/consultancies in the niche.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"}, "location": {"type": "string"},
                "max_results": {"type": "integer"}}, "required": ["query"]},
        }},
        {"type": "function", "function": {
            "name": "fetch_webpage",
            "description": "Fetch a company homepage to extract emails and LinkedIn URLs.",
            "parameters": {"type": "object", "properties": {
                "url": {"type": "string"}, "company_name": {"type": "string"}}, "required": ["url"]},
        }},
    ]
    client = OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
    )
    # Free models with tool-call support, tried in order
    free_models = [
        "meta-llama/llama-3.3-70b-instruct:free",
        "google/gemma-3-27b-it:free",
        "mistralai/mistral-7b-instruct:free",
        "meta-llama/llama-3.1-8b-instruct:free",
    ]
    model = free_models[0]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Find B2B leads in this niche: {niche}"},
    ]
    max_turns = 25
    for turn in range(max_turns):
        for m in free_models:
            try:
                response = client.chat.completions.create(
                    model=m,
                    max_tokens=8096,
                    tools=or_tools,
                    tool_choice="auto",
                    messages=messages,
                )
                model = m
                break
            except Exception as e:
                if any(code in str(e) for code in ["402", "429", "404", "400"]) or "rate" in str(e).lower() or "limit" in str(e).lower():
                    if verbose:
                        print(f"  [OpenRouter] {m} unavailable, trying next model...")
                    continue
                raise
        else:
            print("[OpenRouter] All free models rate-limited.")
            return []
        if not response.choices:
            if verbose:
                print("  [OpenRouter] Empty response, retrying...")
            continue
        msg = response.choices[0].message
        finish_reason = response.choices[0].finish_reason
        assistant_msg: dict = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant_msg["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]
        messages.append(assistant_msg)

        if finish_reason == "stop" or (not msg.tool_calls and msg.content):
            text = msg.content or ""
            leads = _parse_leads_from_text(text)
            if leads is not None:
                return leads
            print(f"[OpenRouter] JSON parse failed. Raw: {text[:300]}")
            return []
        elif msg.tool_calls:
            for tc in msg.tool_calls:
                if verbose:
                    print(f"  [Tool] {tc.function.name}({tc.function.arguments[:120]})")
                result = dispatch_tool(tc.function.name, json.loads(tc.function.arguments))
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    return []


def _find_leads_ollama(niche: str, verbose: bool = False) -> list[Lead]:
    """Ollama local backend — no rate limits, no API key needed."""
    ollama_tools = [
        {"type": "function", "function": {
            "name": "search_google",
            "description": "Search the web using DuckDuckGo. Returns titles, URLs, and snippets.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]},
        }},
        {"type": "function", "function": {
            "name": "search_github",
            "description": "Search GitHub repos or org accounts for companies in the niche.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"},
                "search_type": {"type": "string", "enum": ["repositories", "users"]},
                "max_results": {"type": "integer"}}, "required": ["query"]},
        }},
        {"type": "function", "function": {
            "name": "search_google_maps",
            "description": "Search Google Places for agencies/consultancies in the niche.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"}, "location": {"type": "string"},
                "max_results": {"type": "integer"}}, "required": ["query"]},
        }},
        {"type": "function", "function": {
            "name": "fetch_webpage",
            "description": "Fetch a company homepage to extract emails and LinkedIn URLs.",
            "parameters": {"type": "object", "properties": {
                "url": {"type": "string"}, "company_name": {"type": "string"}}, "required": ["url"]},
        }},
    ]
    # Models tried in order (small enough for 8GB RAM)
    ollama_models = ["llama3.2", "llama3.2:1b", "llama3.1", "mistral", "phi3"]
    client = OpenAI(api_key="ollama", base_url="http://localhost:11434/v1")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Find B2B leads in this niche: {niche}"},
    ]
    # Detect which models are available
    try:
        available = {m.id for m in client.models.list().data}
    except Exception:
        available = set(ollama_models)
    usable_models = [m for m in ollama_models if m in available] or ollama_models

    model = usable_models[0]
    if verbose:
        print(f"  [Ollama] Using model: {model}")

    max_turns = 25
    for turn in range(max_turns):
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=8192,
                tools=ollama_tools,
                tool_choice="auto",
                messages=messages,
            )
        except Exception as e:
            err = str(e)
            # Try next model if current one isn't pulled
            remaining = [m for m in usable_models if m != model]
            if remaining and ("not found" in err.lower() or "404" in err or "pull" in err.lower()):
                model = remaining[0]
                usable_models = remaining
                if verbose:
                    print(f"  [Ollama] Model not found, switching to {model}...")
                continue
            raise RuntimeError(f"Ollama error: {e}")

        msg = response.choices[0].message
        finish_reason = response.choices[0].finish_reason
        assistant_msg: dict = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant_msg["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]
        messages.append(assistant_msg)

        if finish_reason == "stop" or (not msg.tool_calls and msg.content):
            text = msg.content or ""
            # Check for XML-style tool calls (small models sometimes emit these)
            inline_calls = _parse_all_xml_tool_calls(text)
            if inline_calls:
                messages.pop()
                tc_refs, tool_results = [], []
                for fake_id, tool_name, tool_args in inline_calls:
                    if verbose:
                        print(f"  [Tool/inline] {tool_name}({json.dumps(tool_args)[:120]})")
                    result = dispatch_tool(tool_name, tool_args)
                    tc_refs.append({"id": fake_id, "type": "function", "function": {"name": tool_name, "arguments": json.dumps(tool_args)}})
                    tool_results.append({"role": "tool", "tool_call_id": fake_id, "content": result})
                messages.append({"role": "assistant", "content": "", "tool_calls": tc_refs})
                messages.extend(tool_results)
                continue
            leads = _parse_leads_from_text(text)
            if leads is not None:
                return leads
            if verbose:
                print(f"[Ollama] JSON parse failed. Raw: {text[:300]}")
            return []
        elif msg.tool_calls:
            for tc in msg.tool_calls:
                if verbose:
                    print(f"  [Tool] {tc.function.name}({tc.function.arguments[:120]})")
                result = dispatch_tool(tc.function.name, json.loads(tc.function.arguments))
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    return []


def find_leads(niche: str, verbose: bool = False) -> list[Lead]:
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    groq_key = os.environ.get("GROQ_API_KEY", "")
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")

    if gemini_key:
        if verbose:
            print("[Agent] Using Gemini 2.0 Flash\n")
        try:
            return _find_leads_gemini(niche, verbose)
        except ClientError as e:
            if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
                print(f"[Agent] Gemini quota/rate limit: {str(e)[:200]}, falling back to Groq...")
            else:
                raise
    if groq_key:
        if verbose:
            print("[Agent] Using Groq (Llama 3.3 70B)\n")
        try:
            return _find_leads_groq(niche, verbose)
        except Exception as e:
            print(f"[Agent] Groq failed ({str(e)[:100]}), falling back to OpenRouter...")
    if openrouter_key:
        if verbose:
            print("[Agent] Using OpenRouter (Llama 3.3 70B free)\n")
        leads = _find_leads_openrouter(niche, verbose)
        if leads:
            return leads
        print("[Agent] OpenRouter exhausted, falling back to Ollama...")
    # Try Ollama (local, no rate limits)
    try:
        import httpx
        httpx.get("http://localhost:11434", timeout=2)
        if verbose:
            print("[Agent] Using Ollama (local)\n")
        return _find_leads_ollama(niche, verbose)
    except Exception:
        pass
    raise RuntimeError("No API key found or all backends exhausted. Set GEMINI_API_KEY, GROQ_API_KEY, or OPENROUTER_API_KEY in .env, or run Ollama locally.")


def _find_leads_gemini(niche: str, verbose: bool = False) -> list[Lead]:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    history: list[types.Content] = []
    user_msg = types.Content(
        role="user",
        parts=[types.Part(text=f"Find B2B leads in this niche: {niche}")],
    )
    history.append(user_msg)

    if verbose:
        print(f"\n[Agent] Starting lead search for: {niche}\n")

    max_turns = 25
    turn = 0

    while turn < max_turns:
        turn += 1
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=history,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=TOOLS,
                temperature=0.3,
            ),
        )

        candidate = response.candidates[0]
        history.append(candidate.content)

        # Check if there are any function calls
        function_calls = [p for p in candidate.content.parts if p.function_call]

        if not function_calls:
            # No tool calls — model is done, extract text
            text_parts = [p.text for p in candidate.content.parts if p.text]
            text = "\n".join(text_parts).strip()
            if text:
                leads = _parse_leads_from_text(text)
                if leads is not None:
                    return leads
                print(f"[Agent] JSON parse failed. Raw (first 300): {text[:300]}")
            return []

        # Execute all function calls and collect results
        tool_results = []
        for part in candidate.content.parts:
            if not part.function_call:
                continue
            fc = part.function_call
            if verbose:
                args_preview = json.dumps(dict(fc.args))[:120]
                print(f"  [Tool] {fc.name}({args_preview})")
            result_str = dispatch_tool(fc.name, dict(fc.args))
            tool_results.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name,
                        response={"result": result_str},
                    )
                )
            )

        history.append(types.Content(role="user", parts=tool_results))

    if turn >= max_turns:
        print(f"[Agent] Hit max turn limit ({max_turns}). Returning partial results.")
    return []
