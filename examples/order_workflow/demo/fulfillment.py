"""A second component that updates orders and records fulfillment in an outbox."""

from __future__ import annotations

from .store import transaction


def fulfill(event: dict, context: object) -> dict:
    """Fulfill once, leaving duplicate invocations safe in this local workflow."""
    if (
        not isinstance(event, dict)
        or set(event) != {"order_id"}
        or not isinstance(event["order_id"], str)
        or not event["order_id"]
    ):
        return {"status": "invalid_input"}
    order_id = event["order_id"]
    with transaction() as connection:
        order = connection.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        if order is None:
            return {"status": "not_found"}
        if order["status"] == "fulfilled":  # idempotency guard
            return {"status": "fulfilled", "order_id": order_id}

        connection.execute(
            "UPDATE orders SET status = ? WHERE order_id = ?", ("fulfilled", order_id)
        )
        connection.execute(
            "INSERT INTO outbox (order_id, event_type) VALUES (?, ?)",
            (order_id, "OrderFulfilled"),
        )
        return {"status": "fulfilled", "order_id": order_id}
