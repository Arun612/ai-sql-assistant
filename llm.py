"""
llm.py — All Groq LLM interactions:
  1. generate_sql()       — NL question → SQL
  2. explain_results()    — SQL + rows → plain-English summary
  3. explain_sql()        — SQL → what does this query do?
  4. recommend_chart()    — rows + question → chart type suggestion
"""

import os
import json
from groq import Groq
from database import get_schema_context
from safety import sanitize_llm_output

# ── Client ───────────────────────────────────────────────────────────────────

def _client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY environment variable is not set.")
    return Groq(api_key=api_key)

MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")


def _chat(system: str, user: str, max_tokens: int = 512) -> str:
    """Helper: single-turn chat completion."""
    client = _client()
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=max_tokens,
        temperature=0.1,          # low temp = more deterministic SQL
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    )
    return response.choices[0].message.content.strip()


# ── 1. NL → SQL ──────────────────────────────────────────────────────────────

SQL_SYSTEM = """You are an expert SQLite query generator for a business analytics assistant.

{schema}

STRICT RULES:
- Output ONLY the raw SQL query. No explanation, no markdown, no backticks.
- Use only SELECT statements. Never use INSERT, UPDATE, DELETE, DROP, or any write operation.
- Use proper SQLite syntax (strftime for dates, etc.).
- For "last month" use: strftime('%Y-%m', order_date) = strftime('%Y-%m', date('now', '-1 month'))
- For "this month" use: strftime('%Y-%m', order_date) = strftime('%Y-%m', 'now')
- Always qualify column names with table aliases when joining tables.
- If the question is ambiguous, make a reasonable business assumption.
- Limit results to 100 rows unless the user specifies a different LIMIT.
""".strip()


def generate_sql(question: str) -> str:
    """Convert a natural language question to a SQLite SELECT query."""
    system = SQL_SYSTEM.format(schema=get_schema_context())
    raw = _chat(system, question, max_tokens=256)
    return sanitize_llm_output(raw)


# ── 2. Results → Plain-English Explanation ───────────────────────────────────

EXPLAIN_RESULTS_SYSTEM = """You are a friendly business analyst assistant.
You will be given a SQL query, the results it returned, and the original user question.
Write a concise plain-English explanation (2–4 sentences) that a non-technical business user would understand.
Focus on the business insight, not the technical details.
Do not mention SQL, tables, or column names.
If results are empty, say so clearly and suggest why that might be.
""".strip()


def explain_results(question: str, sql: str, results: list[dict]) -> str:
    """Generate a plain-English explanation of query results."""
    # Truncate results preview to avoid token waste
    preview = results[:10]
    user_msg = f"""Original question: {question}

SQL used: {sql}

Results ({len(results)} row(s) total, showing up to 10):
{json.dumps(preview, indent=2, default=str)}
"""
    return _chat(EXPLAIN_RESULTS_SYSTEM, user_msg, max_tokens=300)


# ── 3. SQL → What does this query do? ────────────────────────────────────────

EXPLAIN_SQL_SYSTEM = """You are a SQL tutor explaining queries to a junior analyst.
Given a SQL query, explain in plain English:
1. What data it retrieves
2. Any filters or conditions applied
3. How results are ordered or grouped (if applicable)
Keep it concise (3–5 sentences). No code blocks, just clear prose.
""".strip()


def explain_sql_query(sql: str) -> str:
    """Explain what a SQL query does in plain English."""
    return _chat(EXPLAIN_SQL_SYSTEM, f"Explain this SQL query:\n{sql}", max_tokens=300)


# ── 4. Chart Recommendation ───────────────────────────────────────────────────

CHART_SYSTEM = """You are a data visualization expert.
Given a user question and query results, recommend the best chart type.
Respond ONLY with a JSON object in this exact format (no markdown, no extra text):
{"chart_type": "<type>", "reason": "<one sentence why>", "x_axis": "<column>", "y_axis": "<column>"}

Chart types to choose from: bar, line, pie, scatter, table
If results have only 1 row or are not visual, use "table".
If columns are unclear for x/y, use null for those fields.
""".strip()


def recommend_chart(question: str, results: list[dict]) -> dict:
    """Suggest a chart type for the given results."""
    if not results:
        return {"chart_type": "table", "reason": "No data to visualize.", "x_axis": None, "y_axis": None}

    preview = results[:5]
    columns = list(results[0].keys()) if results else []
    user_msg = f"""Question: {question}
Columns: {columns}
Sample rows: {json.dumps(preview, default=str)}
"""
    raw = _chat(CHART_SYSTEM, user_msg, max_tokens=150)

    # Safely parse JSON response
    try:
        # Strip any accidental markdown
        raw = raw.strip().strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {"chart_type": "table", "reason": "Could not determine chart type.", "x_axis": None, "y_axis": None}
