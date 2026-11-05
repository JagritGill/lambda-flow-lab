"""Create and inspect synthetic orders through a real SQLite adapter."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from .store import transaction


def create(event: dict, context: object) -> dict:
    """Accept an idempotency key, reject conflicting reuse, and persist an order."""
    if not isinstance(event, dict) or set(event) != {"request_id", "sku", "quantity"}:
        return {"status": "invalid_input"}
    request_id, sku, quantity = event["request_id"], event["sku"], event["quantity"]
    if (
        not isinstance(request_id, str)
        or not 1 <= len(request_id) <= 64
        or not isinstance(sku, str)
        or not 1 <= len(sku) <= 64
        or type(quantity) is not int
        or not 1 <= quantity <= 100
    ):
        return {"status": "invalid_input"}

    with transaction() as connection:
        existing = connection.execute(
            "SELECT * FROM orders WHERE request_id = ?", (request_id,)
        ).fetchone()
        if existing is not None:
            if (existing["sku"], existing["quantity"]) != (sku, quantity):
                return {"status": "conflict"}
            return {"status": "existing", "order_id": existing["order_id"]}

        order_id = str(uuid5(NAMESPACE_URL, "synthetic-order:" + request_id))
        connection.execute(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?)",
            (order_id, request_id, sku, quantity, "created"),
        )
        return {"status": "created", "order_id": order_id}


def inspect(event: dict, context: object) -> dict:
    """Read persisted state through a separate connection after earlier invocations.

    This observation handler is a test adapter, not a production administration API.
    It exposes synthetic data only and is not intended for deployment.
    """
    if not isinstance(event, dict) or set(event) - {"order_id"}:
        return {"status": "invalid_input"}
    if "order_id" in event and not isinstance(event["order_id"], str):
        return {"status": "invalid_input"}
    with transaction() as connection:
        if "order_id" in event:
            orders = connection.execute(
                "SELECT * FROM orders WHERE order_id = ? ORDER BY order_id",
                (event["order_id"],),
            ).fetchall()
            outbox = connection.execute(
                "SELECT * FROM outbox WHERE order_id = ? ORDER BY event_id",
                (event["order_id"],),
            ).fetchall()
        else:
            orders = connection.execute("SELECT * FROM orders ORDER BY order_id").fetchall()
            outbox = connection.execute("SELECT * FROM outbox ORDER BY event_id").fetchall()
        return {
            "status": "observed",
            "orders": [dict(row) for row in orders],
            "outbox": [dict(row) for row in outbox],
        }
