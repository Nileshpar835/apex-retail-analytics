"""Convert raw Brigade POS export into challenge pos_transactions.csv format."""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    raw_path = root / "data" / "pos_raw.csv"
    out_path = root / "data" / "pos_transactions.csv"

    invoices: dict[str, dict] = {}
    with raw_path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            invoice = row["invoice_number"]
            order_date = row["order_date"]
            order_time = row["order_time"]
            dt = datetime.strptime(f"{order_date} {order_time}", "%d-%m-%Y %H:%M:%S")
            dt_utc = dt.replace(tzinfo=timezone.utc)
            amount = float(row.get("total_amount") or 0)
            invoices.setdefault(
                invoice,
                {
                    "store_id": "STORE_BLR_002",
                    "transaction_id": invoice,
                    "timestamp": dt_utc.isoformat().replace("+00:00", "Z"),
                    "basket_value_inr": 0.0,
                },
            )
            invoices[invoice]["basket_value_inr"] += amount

    rows = sorted(invoices.values(), key=lambda item: item["timestamp"])
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["store_id", "transaction_id", "timestamp", "basket_value_inr"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} transactions to {out_path}")


if __name__ == "__main__":
    main()
