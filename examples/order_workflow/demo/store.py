"""Real local persistence shared by the example's independent handlers.

SQLite is deliberately a local adapter, not a DynamoDB emulator. The transaction
boundaries here prove nothing about distributed retries or concurrent AWS writes.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Open a connection to this scenario's isolated database and commit or roll back."""
    root = Path(os.environ["FLOW_LAB_STATE_DIR"])
    root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(root / "orders.sqlite3")
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL UNIQUE,
                sku TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outbox (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                event_type TEXT NOT NULL
            );
            """
        )
        with connection:
            yield connection
    finally:
        connection.close()
