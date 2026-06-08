"""
app.py — FastAPI application entry point
AI-powered SQL Assistant: NL → SQL → Execute → Explain
"""
from dotenv import load_dotenv
load_dotenv()

import time
import sqlite3
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from database import init_db, execute_query, get_schema_context
from safety import validate_sql, inject_limit
from llm import generate_sql, generate_sql_with_retry, explain_results, explain_sql_query, recommend_chart
from logger import log_query, get_logs


# ── Lifespan (startup/shutdown) ───────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[Startup] Initialising database...")
    init_db()
    print("[Startup] Ready.")
    yield
    print("[Shutdown] Bye.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI SQL Assistant",
    description=(
        "Convert natural language questions into SQL, execute them safely, "
        "and get plain-English explanations of the results."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response Models ─────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=3,
        max_length=500,
        example="Show top 5 customers by number of orders",
    )
    include_chart_suggestion: bool = Field(
        default=True,
        description="Whether to include a chart type recommendation.",
    )


class QueryResponse(BaseModel):
    sql:         str
    results:     list[dict]
    explanation: str
    row_count:   int
    duration_ms: float
    chart:       Optional[dict] = None


class ExplainSQLRequest(BaseModel):
    sql: str = Field(..., min_length=6, max_length=2000, example="SELECT * FROM customers LIMIT 5")


class ExplainSQLResponse(BaseModel):
    sql:         str
    explanation: str
    is_safe:     bool
    safety_note: Optional[str] = None


class ErrorResponse(BaseModel):
    error:  str
    detail: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
def health_check():
    """Simple liveness check."""
    return {"status": "ok", "version": "1.0.0"}


@app.get("/schema", tags=["System"])
def get_schema():
    """Return the database schema context (useful for debugging)."""
    return {"schema": get_schema_context()}


# ── POST /query ───────────────────────────────────────────────────────────────

@app.post(
    "/query",
    tags=["Query"],
    summary="Convert a natural language question to SQL and execute it",
)
def query(body: QueryRequest):
    start = time.perf_counter()
    question = body.question.strip()

    # ── Step 1: Generate SQL ─────────────────────────────────────────────────
    try:
        sql = generate_sql(question)
    except Exception as e:
        log_query(question, None, None, False, f"LLM error: {e}")
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": "LLM_ERROR",
                "message": "LLM service error while generating SQL.",
                "detail": str(e),
            }
        )

    if not sql:
        log_query(question, sql, None, False, "LLM returned empty SQL")
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "EMPTY_SQL",
                "message": "The model could not generate a SQL query for this question.",
                "detail": "Try rephrasing your question.",
            }
        )

    # ── Step 2: Safety Validation ────────────────────────────────────────────
    validation = validate_sql(sql)
    if not validation.is_safe:
        log_query(question, sql, None, False, f"Safety: {validation.reason}")
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "SQL_SAFETY_VIOLATION",
                "message": "Generated SQL failed safety check.",
                "detail": validation.reason,
            }
        )

    # ── Step 3: Auto-inject LIMIT ────────────────────────────────────────────
    sql = inject_limit(sql)

    # ── Step 4: Execute Query (with one retry on failure) ────────────────────
    try:
        results = execute_query(sql)
    except sqlite3.Error as e:
        # Retry once with error context
        print(f"[SQL] Execution failed: {e}. Retrying with error context...")
        try:
            sql = generate_sql_with_retry(question, str(e))
            validation = validate_sql(sql)
            if not validation.is_safe:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error_code": "SQL_SAFETY_VIOLATION",
                        "message": "Retried SQL failed safety check.",
                        "detail": validation.reason,
                    }
                )
            sql = inject_limit(sql)
            results = execute_query(sql)
        except sqlite3.Error as e2:
            log_query(question, sql, None, False, f"SQLite retry failed: {e2}")
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "SQL_EXECUTION_ERROR",
                    "message": "SQL execution failed after retry.",
                    "detail": str(e2),
                }
            )

    elapsed_ms = (time.perf_counter() - start) * 1000

    # ── Step 5: Explain Results ──────────────────────────────────────────────
    try:
        explanation = explain_results(question, sql, results)
    except Exception:
        explanation = f"Query returned {len(results)} row(s)."

    # ── Step 6: Chart Recommendation ────────────────────────────────────────
    chart = None
    if body.include_chart_suggestion and results:
        try:
            chart = recommend_chart(question, results)
        except Exception:
            chart = None

    # ── Step 7: Log & Return ─────────────────────────────────────────────────
    log_query(question, sql, len(results), True, duration_ms=elapsed_ms)

    return QueryResponse(
        sql=sql,
        results=results,
        explanation=explanation,
        row_count=len(results),
        duration_ms=round(elapsed_ms, 2),
        chart=chart,
    )


# ── GET /history ──────────────────────────────────────────────────────────────

@app.get(
    "/history",
    tags=["Audit"],
    summary="Retrieve recent query history",
)
def history(limit: int = Query(default=20, ge=1, le=100)):
    """
    Returns the most recent query log entries (newest first).
    Each entry includes the original question, generated SQL, result count,
    success status, and execution time.
    """
    return {"logs": get_logs(limit=limit), "count": limit}


# ── POST /explain-sql ─────────────────────────────────────────────────────────

@app.post(
    "/explain-sql",
    response_model=ExplainSQLResponse,
    tags=["Query"],
    summary="Explain what a SQL query does in plain English",
)
def explain_sql(body: ExplainSQLRequest):
    """
    Paste any SQL query and receive a plain-English explanation of what it does.
    The safety check still runs — unsafe queries are flagged but still explained.
    """
    sql = body.sql.strip()
    validation = validate_sql(sql)

    try:
        explanation = explain_sql_query(sql)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {str(e)}")

    return ExplainSQLResponse(
        sql=sql,
        explanation=explanation,
        is_safe=validation.is_safe,
        safety_note=None if validation.is_safe else validation.reason,
    )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
