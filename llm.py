"""
llm.py — All Groq LLM interactions:
  1. generate_sql()       — NL question → SQL
  2. explain_results()    — SQL + rows → plain-English summary
  3. explain_sql()        — SQL → what does this query do?
  4. recommend_chart()    — rows + question → chart type suggestion
"""

import os
import json
import time
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
    """Helper: single-turn chat completion with rate limit retry."""
    client = _client()
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                max_tokens=max_tokens,
                temperature=0.1,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            error_str = str(e).lower()
            if "rate_limit" in error_str and attempt < 2:
                wait = 2 ** attempt   # 1s, 2s
                print(f"[Groq] Rate limit hit, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


# ── 1. NL → SQL ──────────────────────────────────────────────────────────────

SQL_SYSTEM = """You are an expert SQLite query generator for a business analytics assistant.

{schema}

STRICT RULES:
- Output ONLY the raw SQL query. No explanation, no markdown, no backticks.
- Use only SELECT statements. Never use INSERT, UPDATE, DELETE, DROP, or any write operation.
- Use proper SQLite syntax (strftime for dates, etc.).
- For "last month" use: strftime('%Y-%m', order_date) = strftime('%Y-%m', date('now', '-1 month'))
- For "this month" use: strftime('%Y-%m', order_date) = strftime('%Y-%m', 'now')
- ALWAYS include the grouping column in SELECT when using GROUP BY.
- ALWAYS alias aggregations: COUNT(*) AS order_count, SUM(...) AS revenue, AVG(...) AS avg_price.
- Always qualify column names with table aliases when joining tables.
- Limit results to 100 rows unless the user specifies otherwise.

EXAMPLES:
Q: How many orders were placed last month?
A: SELECT COUNT(*) AS order_count FROM orders WHERE strftime('%Y-%m', order_date) = strftime('%Y-%m', date('now', '-1 month'))

Q: Show top 5 customers by number of orders
A: SELECT c.name, COUNT(o.id) AS order_count FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.id, c.name ORDER BY order_count DESC LIMIT 5

Q: What is the total revenue by product category?
A: SELECT p.category, SUM(p.price * o.quantity) AS revenue FROM orders o JOIN products p ON o.product_id = p.id GROUP BY p.category ORDER BY revenue DESC

Q: Which city has the most customers?
A: SELECT city, COUNT(*) AS customer_count FROM customers GROUP BY city ORDER BY customer_count DESC LIMIT 10

Q: What is the total number of orders by product category?
A: SELECT p.category, COUNT(*) AS order_count FROM orders o JOIN products p ON o.product_id = p.id GROUP BY p.category ORDER BY order_count DESC

Q: List all electronics products under 5000
A: SELECT name, price FROM products WHERE category = 'Electronics' AND price < 5000 ORDER BY price ASC
""".strip()


def generate_sql(question: str) -> str:
    """Convert a natural language question to a SQLite SELECT query."""
    system = SQL_SYSTEM.format(schema=get_schema_context())
    raw = _chat(system, question, max_tokens=256)
    return sanitize_llm_output(raw)

def generate_sql_with_retry(question: str, error: str) -> str:
    """Retry SQL generation with the execution error as context."""
    system = SQL_SYSTEM.format(schema=get_schema_context())
    user = f"""Question: {question}

    Your previous SQL failed with this error: {error}

    Fix the SQL and return only the corrected query, nothing else."""
    raw = _chat(system, user, max_tokens=256)
    return sanitize_llm_output(raw)


# ── 2. Results → Plain-English Explanation ───────────────────────────────────

EXPLAIN_RESULTS_SYSTEM = """You are a friendly business analyst assistant.
You will be given a SQL query, the results it returned, and the original user question.
Write a concise plain-English explanation (2-4 sentences) that a non-technical business user would understand.

RULES:
- Always mention specific values and numbers from the results. Never say "several" or "many" — use actual figures.
- Always name the top/bottom items explicitly (e.g. "Electronics leads with 61 orders").
- For prices, revenue, or any monetary amounts, always use Indian Rupees: prefix with ₹ (e.g. ₹1,200). Never use $, USD, or dollars.
- Focus on the business insight, not technical details.
- Do not mention SQL, tables, column names, or database terms.
- If results are empty, say so clearly and suggest a likely reason.
- If there is only one row, summarize it in one sentence.

EXAMPLES:
Results: [{"category": "Electronics", "order_count": 61}, {"category": "Stationery", "order_count": 45}]
Good: "Electronics is the most ordered category with 61 orders, followed by Stationery with 45. Books has the least demand at 27 orders."

Results: [{"name": "Wireless Mouse", "price": 1200}, {"name": "USB-C Hub", "price": 2800}]
Good: "Wireless Mouse is the cheapest at ₹1,200, followed by USB-C Hub at ₹2,800."
Bad: "The cheapest product costs $1200."
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

EXPLAIN_SQL_SYSTEM = """You are a SQL tutor explaining queries to a junior business analyst.
Given a SQL query, explain it in plain English covering these points:
1. What data it retrieves (which entities/metrics)
2. Any filters or conditions applied
3. How results are grouped, ordered, or limited

RULES:
- Use simple business language, no technical jargon.
- Be concise — 3 to 5 sentences maximum.
- Do not use bullet points, just clear flowing prose.
- Do not repeat the SQL back to the user.
""".strip()

def explain_sql_query(sql: str) -> str:
    """Explain what a SQL query does in plain English."""
    return _chat(EXPLAIN_SQL_SYSTEM, f"Explain this SQL query:\n{sql}", max_tokens=300)


# ── 4. Chart Recommendation ───────────────────────────────────────────────────

CHART_SYSTEM = """You are a data visualization expert.
Given a user question and query results, recommend the best chart type.

RULES:
- pie: use when data shows proportions, distributions, or breakdowns by category (≤8 groups)
- line: use when data has a time dimension (months, days, years, trends over time)
- bar: use when comparing values across named categories without time
- scatter: use when showing correlation between two numeric values
- table: use only when there is a single row, or data does not suit any chart

EXAMPLES:
Q: Orders by product category → pie (proportions across categories)
Q: Revenue per month → line (time series)
Q: Top 5 customers by orders → bar (comparing named entities)
Q: Total orders last month → table (single value)
Q: Orders by city → pie (distribution across cities, ≤8 values)
Q: Daily sales trend → line (time dimension)

Respond ONLY with a JSON object, no markdown, no extra text:
{"chart_type": "<type>", "reason": "<one sentence why>", "x_axis": "<column or null>", "y_axis": "<column or null>"}
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
