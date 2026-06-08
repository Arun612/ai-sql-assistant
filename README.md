# AI SQL Assistant

An internal analytics assistant that converts natural language questions into SQL, executes them safely against a SQLite database, and returns plain-English explanations of the results.

Built with **Python** + **FastAPI** + **Groq (llama-3.1-8b-instant)** + **SQLite**.

---

## Features

- **NL → SQL** — Groq LLM with schema-aware prompting and six few-shot examples
- **SQL Safety Validation** — SELECT-only enforcement, keyword blocklist, multi-statement detection
- **LIMIT auto-injection** — appends `LIMIT 100` when the generated query has no limit
- **SQL execution retry** — on SQLite error, regenerates SQL once using the error as context
- **Groq rate-limit retry** — up to 3 attempts with exponential backoff (1s, 2s)
- **Typed error codes** — structured `error_code` in all `/query` error responses
- **Plain-English Explanations** — results summarised for non-technical users
- **Chart Recommendations** — suggests bar / line / pie / table based on result shape
- **Query History** — full audit log in `query_logs.json`
- **`/explain-sql` endpoint** — explains any SQL query in plain English
- **Auto-seeded database** — 40 customers, 20 products, 200 orders on first run
- **Docker support**

---

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/your-username/ai-sql-assistant.git
cd ai-sql-assistant

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Set Environment Variables

Create a `.env` file in the project root:

```env
GROQ_API_KEY=your_groq_api_key_here
```

Get a free Groq API key at https://console.groq.com

### 3. Run

```bash
python app.py
# or
uvicorn app:app --reload
```

On first startup, `database.db` is created from `schema.sql` and seeded automatically.

Server starts at `http://localhost:8000`  
Interactive docs at `http://localhost:8000/docs`

---

## Docker

```bash
# Build
docker build -t ai-sql-assistant .

# Run
docker run -p 8000:8000 -e GROQ_API_KEY=your_key_here ai-sql-assistant
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GROQ_API_KEY` | *(required)* | Your Groq API key |
| `GROQ_MODEL` | `llama-3.1-8b-instant` | Groq model to use |
| `DB_PATH` | `database.db` | Path to SQLite database file |
| `LOG_PATH` | `query_logs.json` | Path to query audit log |

**To use a larger model** (better accuracy, slower): set `GROQ_MODEL=llama-3.3-70b-versatile`

---

## API Reference

### `POST /query`

Convert a natural language question to SQL and get results.

**Request:**
```json
{
  "question": "Show top 5 customers by number of orders",
  "include_chart_suggestion": true
}
```

**Response:**
```json
{
  "sql": "SELECT c.name, COUNT(o.id) AS order_count FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.id, c.name ORDER BY order_count DESC LIMIT 5",
  "results": [
    {
      "name": "Rahul Kumar",
      "order_count": 11
    },
    {
      "name": "Priya Kumar",
      "order_count": 9
    },
    {
      "name": "Sneha Nair",
      "order_count": 9
    },
    {
      "name": "Arjun Patel",
      "order_count": 8
    },
    {
      "name": "Sneha Joshi",
      "order_count": 8
    }
  ],
  "explanation": "Rahul Kumar leads the top customers with 11 orders, followed closely by Priya Kumar and Sneha Nair with 9 orders each. Arjun Patel and Sneha Joshi come in fourth and fifth with 8 orders each.",
  "row_count": 5,
  "duration_ms": 434.51,
  "chart": {
    "chart_type": "bar",
    "reason": "comparing values across named categories without time",
    "x_axis": "name",
    "y_axis": "order_count"
  }
}
```

**Error response** (structured `detail` object):

```json
{
  "detail": {
    "error_code": "SQL_SAFETY_VIOLATION",
    "message": "Generated SQL failed safety check.",
    "detail": "Only SELECT queries are allowed. Got: 'DELETE'."
  }
}
```

| HTTP Status | `error_code` | When |
|-------------|--------------|------|
| 400 | `SQL_SAFETY_VIOLATION` | Generated or retried SQL fails safety validation |
| 422 | `EMPTY_SQL` | LLM returned no usable SQL |
| 422 | `SQL_EXECUTION_ERROR` | SQLite execution failed after one retry |
| 502 | `LLM_ERROR` | Groq API failure during SQL generation |

---

### `GET /history?limit=20`

Returns recent query audit log entries (newest first).

**Response:**
```json
{
  "logs": [
    {
      "id": 5,
      "timestamp": "2026-06-08T10:30:00Z",
      "question": "How many orders last month?",
      "sql": "SELECT COUNT(*) FROM orders WHERE ...",
      "results_count": 1,
      "success": true,
      "error": null,
      "duration_ms": 712.4
    }
  ],
  "count": 20
}
```

---

### `POST /explain-sql`

Explain what a SQL query does in plain English.

**Request:**
```json
{
  "sql": "SELECT c.name, SUM(p.price * o.quantity) AS revenue FROM orders o JOIN customers c ON o.customer_id = c.id JOIN products p ON o.product_id = p.id GROUP BY c.id ORDER BY revenue DESC LIMIT 10"
}
```

**Response:**
```json
{
  "sql": "SELECT c.name ...",
  "explanation": "This query calculates the total revenue generated by each customer by multiplying the price of each product by the quantity ordered. Results are ranked from highest to lowest spend, showing the top 10 customers.",
  "is_safe": true,
  "safety_note": null
}
```

Unsafe queries are still explained but flagged with `is_safe: false` and a `safety_note`.

---

### `GET /health`

```json
{"status": "ok", "version": "1.0.0"}
```

### `GET /schema`

Returns the schema context string injected into every LLM prompt (useful for debugging).

---

## Sample Questions

| Question | Expected behaviour |
|----------|-------------------|
| How many orders were placed last month? | COUNT with strftime filter |
| Show top 5 customers by number of orders | JOIN + GROUP BY + ORDER BY + LIMIT |
| What is the total revenue by product category? | JOIN 3 tables + SUM + GROUP BY |
| Which city has the most customers? | GROUP BY + ORDER BY |
| List all electronics products under ₹5000 | WHERE with category + price filter |
| What is the average order value? | JOIN + AVG calculation |

---

## Database Schema

```sql
customers(id, name, email, city, created_at)
products(id, name, category, price)
orders(id, customer_id, product_id, quantity, order_date)
```

Relationships: `orders.customer_id → customers.id`, `orders.product_id → products.id`

Seeded with: **40 customers · 20 products · 200 orders** (spread over last 90 days, `random.seed(42)`)

`database.db` is auto-created on first run. Run the app once locally if you need the file before committing to the repository.

---

## SQL Safety Rules

The following operations are **always rejected**, regardless of how they appear in a query:

`DELETE` `UPDATE` `INSERT` `DROP` `ALTER` `TRUNCATE` `ATTACH` `DETACH` `CREATE` `REPLACE` `PRAGMA` `VACUUM`

Additional checks:
- Query must start with `SELECT`
- Multi-statement queries (`;` followed by another statement) are blocked
- SQL comments (`--`, `/*`) are blocked
- Maximum query length: 2000 characters
- **LIMIT auto-injection** — if no `LIMIT` clause is present, `LIMIT 100` is appended before execution

---

## Architecture

```
POST /query
    │
    ├─ [1] Input validation (Pydantic)
    ├─ [2] NL → SQL  (Groq LLM, schema + few-shot examples in system prompt)
    ├─ [3] SQL safety check (blocklist + SELECT enforcement)
    ├─ [4] LIMIT auto-injection (default 100)
    ├─ [5] Execute against SQLite
    │       └─ on error → regenerate SQL with error context → re-validate → retry once
    ├─ [6] Results → plain-English explanation (Groq LLM)
    ├─ [7] Chart type recommendation (Groq LLM, optional)
    ├─ [8] Audit log entry written to query_logs.json
    └─ [9] JSON response returned
```

### Key design decisions

**Two-stage LLM design** — SQL generation and result explanation use separate API calls with tightly scoped system prompts. This keeps each call focused and improves output quality from the smaller model.

**Schema always in context** — Full table definitions, column types, foreign-key relationships, and today's date are injected into every SQL generation prompt to prevent hallucinated column names.

**Few-shot prompting** — Six worked Q→A examples in the system prompt cover counts, joins, aggregations, rankings, and filtered lists.

**Separate explanation call** — Up to 10 result rows are sent to a business-focused prompt. If the LLM call fails, a simple row-count fallback is returned instead of failing the request.

**Resilience** — Groq rate-limit errors retry up to 3 times (1s / 2s backoff). SQLite execution errors trigger one SQL regeneration attempt with the error message as context.

**Stateless API** — Each `/query` request is independent. There is no session or conversational memory.

---

## Limitations & Assumptions

### Assumptions

- Questions target the three seeded tables only (`customers`, `products`, `orders`).
- Relative dates ("last month", "this month") resolve against SQLite `date('now')`.
- Revenue is approximated as `price × quantity` — no discounts, taxes, or shipping.
- A single Groq API key is provided via environment variable; no auth layer is included.

### Limitations

- **No conversational follow-up** — multi-turn questions require full context in a single `question` string.
- **Model size** — `llama-3.1-8b-instant` handles straightforward queries well; use `llama-3.3-70b-versatile` for complex analytics.
- **SQLite only** — local file database; production would swap `database.py` to PostgreSQL or similar.
- **Flat-file logging** — `query_logs.json` is not concurrent-safe under heavy parallel load.
- **Blocklist safety** — catches known dangerous patterns but is not a full SQL parser.
- **Chart suggestions** — LLM recommendation only; not a rendered chart. Falls back to `table` on parse failure.
- **Groq rate limits** — free tier ~30 req/min; built-in retry handles transient limits, sustained traffic needs queuing or a paid plan.
- **LLM variability** — seed data is deterministic, but generated SQL and explanations may vary slightly between runs.

---

## Project Structure

```
ai-sql-assistant/
├── app.py            # FastAPI routes, error codes, query pipeline
├── database.py       # SQLite connection, schema context, seeding, execution
├── llm.py            # Groq API: SQL gen, retry, explanation, chart, rate-limit backoff
├── safety.py         # SQL validation, LIMIT injection, output sanitisation
├── logger.py         # JSON audit log read/write
├── schema.sql        # DDL for the three tables
├── database.db       # SQLite DB (auto-created on first run)
├── query_logs.json   # Audit log (auto-created on first query, optional)
├── requirements.txt
├── Dockerfile
└── README.md
```

---

## Sample Outputs

Captured from a running instance against the seeded database.

### 1. Single value query

**Question:** "How many orders were placed last month?"

```json
{
  "sql": "SELECT COUNT(*) AS order_count FROM orders WHERE strftime('%Y-%m', order_date) = strftime('%Y-%m', date('now', '-1 month'))",
  "results": [{"order_count": 70}],
  "explanation": "70 orders were placed last month.",
  "row_count": 1,
  "duration_ms": 4466.15,
  "chart": {"chart_type": "table", "reason": "Single value result.", "x_axis": null, "y_axis": null}
}
```

### 2. JOIN query with bar chart

**Question:** "Show top 5 customers by number of orders"

```json
{
  "sql": "SELECT customers.name, COUNT(orders.id) AS num_orders FROM customers JOIN orders ON customers.id = orders.customer_id GROUP BY customers.id ORDER BY num_orders DESC LIMIT 5",
  "results": [
    {"name": "Rahul Kumar", "num_orders": 11},
    {"name": "Sneha Nair",  "num_orders": 9},
    {"name": "Priya Kumar", "num_orders": 9},
    {"name": "Sneha Joshi", "num_orders": 8},
    {"name": "Arjun Patel", "num_orders": 8}
  ],
  "explanation": "Rahul Kumar leads with 11 orders, followed by Sneha Nair and Priya Kumar with 9 each.",
  "row_count": 5,
  "duration_ms": 550.11,
  "chart": {"chart_type": "bar", "reason": "Comparing order counts across customers.", "x_axis": "name", "y_axis": "num_orders"}
}
```

### 3. 3-table JOIN with aggregation

**Question:** "What is the average order value for each city?"

```json
{
  "sql": "SELECT c.city, AVG(p.price * o.quantity) AS avg_order_value FROM customers c JOIN orders o ON c.id = o.customer_id JOIN products p ON o.product_id = p.id GROUP BY c.city",
  "results": [
    {"city": "Ahmedabad", "avg_order_value": 60410.0},
    {"city": "Bangalore", "avg_order_value": 7204.12},
    {"city": "Chennai",   "avg_order_value": 18096.07}
  ],
  "explanation": "Ahmedabad has the highest average order value at ₹60,410 while Bangalore has the lowest at ₹7,204.",
  "row_count": 10,
  "duration_ms": 1892.57,
  "chart": {"chart_type": "bar", "reason": "Comparing average order values across cities.", "x_axis": "city", "y_axis": "avg_order_value"}
}
```

### 4. Distribution query with pie chart

**Question:** "Show the distribution of customers across cities"

```json
{
  "sql": "SELECT city, COUNT(*) AS customer_count FROM customers GROUP BY city ORDER BY customer_count DESC",
  "results": [
    {"city": "Surat",     "customer_count": 6},
    {"city": "Jaipur",    "customer_count": 5},
    {"city": "Delhi",     "customer_count": 5}
  ],
  "explanation": "Surat leads with 6 customers, followed by Jaipur, Delhi, and Chennai with 5 each.",
  "row_count": 10,
  "duration_ms": 441.53,
  "chart": {"chart_type": "pie", "reason": "Distribution across cities suits a pie chart.", "x_axis": "city", "y_axis": "customer_count"}
}
```

### 5. Safety block

**Question:** "Delete all customers from the database"

**HTTP Status:** 400 Bad Request

```json
{
  "detail": {
    "error_code": "SQL_SAFETY_VIOLATION",
    "message": "Generated SQL failed safety check.",
    "detail": "Only SELECT queries are allowed. Got: 'DELETE'."
  }
}
```
