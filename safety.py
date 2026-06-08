"""
safety.py — SQL safety validation (blocklist + structure checks)
Only SELECT queries are permitted. All destructive or schema-altering
operations are rejected before they ever reach the database.
"""

import re
from dataclasses import dataclass


# ── Blocklist ────────────────────────────────────────────────────────────────

FORBIDDEN_KEYWORDS = [
    "DELETE", "UPDATE", "INSERT", "DROP", "ALTER", "TRUNCATE",
    "ATTACH", "DETACH", "CREATE", "REPLACE", "MERGE", "UPSERT",
    "PRAGMA", "VACUUM", "REINDEX", "ANALYZE", "GRANT", "REVOKE",
    "EXEC", "EXECUTE", "CALL", "LOAD", "IMPORT",
    # SQLite specific attack vectors
    "SQLITE_MASTER", "SQLITE_TEMP_MASTER",
]

# Patterns that could be used for injection
SUSPICIOUS_PATTERNS = [
    r"--",           # SQL comment (could hide injected code)
    r"/\*",          # Block comment start
    r";\s*\w",       # Multiple statements (semicolon followed by another statement)
    r"UNION\s+ALL\s+SELECT.*FROM\s+sqlite",  # SQLite internals via UNION
]


@dataclass
class ValidationResult:
    is_safe: bool
    reason: str = ""


def validate_sql(sql: str) -> ValidationResult:
    """
    Returns ValidationResult(is_safe=True) if the SQL is a safe read-only
    SELECT query, otherwise ValidationResult(is_safe=False, reason=...).
    """
    if not sql or not sql.strip():
        return ValidationResult(False, "Empty SQL query.")

    cleaned = sql.strip()

    # ── 1. Must start with SELECT ────────────────────────────────────────────
    first_token = cleaned.split()[0].upper()
    if first_token != "SELECT":
        return ValidationResult(
            False,
            f"Only SELECT queries are allowed. Got: '{first_token}'."
        )

    # ── 2. Blocklist check (whole-word match, case-insensitive) ──────────────
    sql_upper = cleaned.upper()
    for keyword in FORBIDDEN_KEYWORDS:
        # Use word boundary so "INSERTION" doesn't trip on "INSERT"
        pattern = rf"\b{re.escape(keyword)}\b"
        if re.search(pattern, sql_upper):
            return ValidationResult(
                False,
                f"Forbidden keyword detected: '{keyword}'. Only read-only queries are permitted."
            )

    # ── 3. Suspicious pattern check ──────────────────────────────────────────
    for pattern in SUSPICIOUS_PATTERNS:
        if re.search(pattern, cleaned, re.IGNORECASE):
            return ValidationResult(
                False,
                f"Suspicious SQL pattern detected. Query rejected for safety."
            )

    # ── 4. Length sanity check ───────────────────────────────────────────────
    if len(cleaned) > 2000:
        return ValidationResult(
            False,
            "Query exceeds maximum allowed length of 2000 characters."
        )

    return ValidationResult(True)


def sanitize_llm_output(raw: str) -> str:
    """
    Strip markdown fences, leading/trailing whitespace, and any
    accidental prose that a small model might prepend/append.
    Returns just the SQL string.
    """
    # Remove ```sql ... ``` or ``` ... ``` fences
    raw = re.sub(r"```(?:sql)?", "", raw, flags=re.IGNORECASE)
    raw = raw.strip().strip("`").strip()

    # If the model added an explanation after the SQL, take only up to the
    # first blank line after the SELECT statement
    lines = raw.splitlines()
    sql_lines = []
    for line in lines:
        sql_lines.append(line)
        # Stop collecting after a line ending the statement
        stripped = line.strip()
        if stripped.endswith(";"):
            break

    result = "\n".join(sql_lines).strip()

    # Remove trailing semicolon (SQLite doesn't need it, cleaner for logging)
    result = result.rstrip(";").strip()

    return result

def inject_limit(sql: str, default_limit: int = 100) -> str:
    """
    Auto-inject LIMIT if the query doesn't already have one.
    Prevents accidental full-table dumps.
    """
    if "LIMIT" not in sql.upper():
        return f"{sql} LIMIT {default_limit}"
    return sql