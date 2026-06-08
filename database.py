"""
database.py — SQLite connection, seeding, and query execution
"""

import sqlite3
import json
import os
from datetime import date, timedelta
import random

DB_PATH = os.getenv("DB_PATH", "database.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


# ── Schema string (injected into every LLM prompt) ──────────────────────────

SCHEMA_CONTEXT = """
Tables available in the SQLite database:

customers(id INTEGER, name TEXT, email TEXT, city TEXT, created_at DATE)
products(id INTEGER, name TEXT, category TEXT, price REAL)
orders(id INTEGER, customer_id INTEGER, product_id INTEGER, quantity INTEGER, order_date DATE)

Relationships:
- orders.customer_id → customers.id
- orders.product_id  → products.id

Date format used: YYYY-MM-DD
Today's date: {today}
""".strip()


def get_schema_context() -> str:
    return SCHEMA_CONTEXT.format(today=date.today().isoformat())


# ── Connection ───────────────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row          # rows behave like dicts
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ── Initialise & Seed ────────────────────────────────────────────────────────

def init_db():
    """Create tables and seed sample data if the DB is empty."""
    conn = get_connection()
    with open(SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    conn.commit()

    # Only seed if tables are empty
    cur = conn.execute("SELECT COUNT(*) FROM customers")
    if cur.fetchone()[0] == 0:
        _seed(conn)
    conn.close()


def _seed(conn: sqlite3.Connection):
    """Insert realistic sample data."""
    random.seed(42)

    cities      = ["Mumbai", "Delhi", "Bangalore", "Chennai", "Hyderabad",
                   "Pune", "Kolkata", "Ahmedabad", "Jaipur", "Surat"]
    first_names = ["Aarav", "Vivaan", "Aditya", "Priya", "Ananya",
                   "Rahul", "Sneha", "Karthik", "Divya", "Rohan",
                   "Meera", "Arjun", "Pooja", "Vikram", "Neha"]
    last_names  = ["Sharma", "Patel", "Iyer", "Kumar", "Singh",
                   "Reddy", "Nair", "Joshi", "Mehta", "Gupta"]

    # ── Customers (40) ──────────────────────────────────────────────────────
    customers = []
    used_emails = set()
    for i in range(40):
        fn = random.choice(first_names)
        ln = random.choice(last_names)
        email_base = f"{fn.lower()}.{ln.lower()}"
        email = f"{email_base}{i}@example.com"
        while email in used_emails:
            email = f"{email_base}{i}_{random.randint(1,99)}@example.com"
        used_emails.add(email)
        days_ago = random.randint(30, 730)
        created = (date.today() - timedelta(days=days_ago)).isoformat()
        customers.append((f"{fn} {ln}", email, random.choice(cities), created))

    conn.executemany(
        "INSERT INTO customers(name, email, city, created_at) VALUES (?,?,?,?)",
        customers
    )

    # ── Products (20) ───────────────────────────────────────────────────────
    products = [
        ("Laptop Pro 15",      "Electronics",   85000.00),
        ("Wireless Mouse",     "Electronics",    1200.00),
        ("Mechanical Keyboard","Electronics",    4500.00),
        ("USB-C Hub",          "Electronics",    2800.00),
        ("Monitor 27\"",       "Electronics",   22000.00),
        ("Office Chair",       "Furniture",     12000.00),
        ("Standing Desk",      "Furniture",     28000.00),
        ("Desk Lamp",          "Furniture",      1800.00),
        ("Notebook Set",       "Stationery",      350.00),
        ("Ballpoint Pens 10pk","Stationery",      120.00),
        ("Sticky Notes 5pk",   "Stationery",      180.00),
        ("Whiteboard A1",      "Stationery",     2200.00),
        ("Python Cookbook",    "Books",          1200.00),
        ("Clean Code",         "Books",           950.00),
        ("System Design",      "Books",          1500.00),
        ("Noise Cancelling Headphones","Electronics",8500.00),
        ("Webcam HD",          "Electronics",    3200.00),
        ("Ergonomic Mouse Pad","Accessories",     650.00),
        ("Cable Management Kit","Accessories",    890.00),
        ("Laptop Stand",       "Accessories",    2100.00),
    ]
    conn.executemany(
        "INSERT INTO products(name, category, price) VALUES (?,?,?)",
        products
    )

    # ── Orders (200) ────────────────────────────────────────────────────────
    orders = []
    today = date.today()
    for _ in range(200):
        cust_id  = random.randint(1, 40)
        prod_id  = random.randint(1, 20)
        qty      = random.randint(1, 5)
        # spread orders across last 90 days (ensures "last month" has data)
        days_ago = random.randint(0, 90)
        order_dt = (today - timedelta(days=days_ago)).isoformat()
        orders.append((cust_id, prod_id, qty, order_dt))

    conn.executemany(
        "INSERT INTO orders(customer_id, product_id, quantity, order_date) VALUES (?,?,?,?)",
        orders
    )

    conn.commit()
    print(f"[DB] Seeded: 40 customers, 20 products, 200 orders")


# ── Query Execution ──────────────────────────────────────────────────────────

def execute_query(sql: str) -> list[dict]:
    """
    Execute a validated SELECT query and return rows as a list of dicts.
    Raises sqlite3.Error on failure.
    """
    conn = get_connection()
    try:
        cursor = conn.execute(sql)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
