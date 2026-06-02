"""Generate store events from real POS transaction data.

Each transaction represents a customer journey through the store.
Customers are counted once per visit, tracking their path through multiple cameras.
"""

from __future__ import annotations

import csv
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator


def generate_events_from_pos() -> list[dict]:
    """Convert POS transactions into multi-camera store events.
    
    Each unique customer per day gets one ENTRY event, zone visits, and billing.
    Same customer across multiple cameras = ONE visitor count per day.
    """
    root = Path(__file__).parent.parent
    pos_file = root / "data" / "pos_raw.csv"  # Use raw file with all customer info
    
    if not pos_file.exists():
        print(f"POS file not found: {pos_file}")
        return []
    
    events: list[dict] = []
    customer_visits: dict[tuple[str, str], datetime] = {}  # (customer_number, date) -> first_transaction_time
    
    with open(pos_file, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                # Parse transaction details
                customer_num = row.get("customer_number", "UNKNOWN").strip()
                order_date_str = row.get("order_date", "").strip()
                order_time_str = row.get("order_time", "").strip()
                customer_name = row.get("customer_name", "Guest").strip()
                product_name = row.get("product_name", "").strip()
                dep_name = row.get("dep_name", "").strip()
                store_id = row.get("store_id", "STORE_BLR_002").strip()
                
                if not order_date_str or not order_time_str:
                    continue
                
                # Parse datetime: format is DD-MM-YYYY HH:MM:SS
                try:
                    dt_str = f"{order_date_str} {order_time_str}"
                    transaction_time = datetime.strptime(dt_str, "%d-%m-%Y %H:%M:%S")
                    transaction_time = transaction_time.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                
                # Create a unique visitor_id from customer number or name
                visitor_id = f"CUST_{customer_num}" if customer_num != "UNKNOWN" else f"GUEST_{customer_name.replace(' ', '_')}"
                
                # Track first visit time per customer per day to create ENTRY event
                visit_key = (customer_num, order_date_str)
                if visit_key not in customer_visits:
                    customer_visits[visit_key] = transaction_time
                    
                    # Create ENTRY event at store entrance (first transaction time)
                    entry_time = transaction_time - timedelta(minutes=2)
                    events.append({
                        "event_id": str(uuid.uuid4()),
                        "store_id": store_id,
                        "camera_id": "CAM 1",  # Entry camera
                        "visitor_id": visitor_id,
                        "event_type": "ENTRY",
                        "timestamp": entry_time.isoformat().replace("+00:00", "Z"),
                        "zone_id": "ENTRY",
                        "dwell_ms": 0,
                        "is_staff": False,
                        "confidence": 0.95,
                        "metadata": {
                            "customer_name": customer_name,
                            "session_seq": 1,
                            "store_section": "Entry"
                        }
                    })
                
                # Map department to zone and camera for zone visit
                zone_map = {
                    "makeup": ("MAKEUP", "CAM 2"),
                    "skin": ("SKINCARE", "CAM 2"),
                    "hair": ("HAIRCARE", "CAM 3"),
                    "bath-and-body": ("PERSONAL_CARE", "CAM 3"),
                    "personal-care": ("PERSONAL_CARE", "CAM 4"),
                }
                
                zone_id, camera_id = zone_map.get(dep_name.lower(), ("SHOPPING_FLOOR", "CAM 2"))
                
                # Create ZONE_ENTER event
                zone_enter_time = transaction_time - timedelta(minutes=1)
                events.append({
                    "event_id": str(uuid.uuid4()),
                    "store_id": store_id,
                    "camera_id": camera_id,
                    "visitor_id": visitor_id,
                    "event_type": "ZONE_ENTER",
                    "timestamp": zone_enter_time.isoformat().replace("+00:00", "Z"),
                    "zone_id": zone_id,
                    "dwell_ms": 0,
                    "is_staff": False,
                    "confidence": 0.92,
                    "metadata": {
                        "customer_name": customer_name,
                        "product": product_name[:50],
                        "department": dep_name,
                        "session_seq": 2,
                        "store_section": zone_id
                    }
                })
                
                # Create ZONE_DWELL event (customer browsing)
                dwell_time = transaction_time
                dwell_ms = 45000  # 45 seconds average browse time
                events.append({
                    "event_id": str(uuid.uuid4()),
                    "store_id": store_id,
                    "camera_id": camera_id,
                    "visitor_id": visitor_id,
                    "event_type": "ZONE_DWELL",
                    "timestamp": dwell_time.isoformat().replace("+00:00", "Z"),
                    "zone_id": zone_id,
                    "dwell_ms": dwell_ms,
                    "is_staff": False,
                    "confidence": 0.90,
                    "metadata": {
                        "customer_name": customer_name,
                        "product_purchased": product_name[:50],
                        "session_seq": 3,
                        "store_section": zone_id
                    }
                })
                
                # Create BILLING event (checkout)
                billing_time = transaction_time + timedelta(minutes=2)
                events.append({
                    "event_id": str(uuid.uuid4()),
                    "store_id": store_id,
                    "camera_id": "CAM 5",  # Checkout/billing camera
                    "visitor_id": visitor_id,
                    "event_type": "BILLING_QUEUE_JOIN",
                    "timestamp": billing_time.isoformat().replace("+00:00", "Z"),
                    "zone_id": "BILLING",
                    "dwell_ms": 0,
                    "is_staff": False,
                    "confidence": 0.98,
                    "metadata": {
                        "customer_name": customer_name,
                        "invoice_number": row.get("invoice_number", ""),
                        "total_amount": row.get("total_amount", "0"),
                        "session_seq": 4,
                        "store_section": "Billing"
                    }
                })
                
                # Create CONVERTED event (billing completed)
                converted_time = billing_time + timedelta(seconds=30)
                events.append({
                    "event_id": str(uuid.uuid4()),
                    "store_id": store_id,
                    "camera_id": "CAM 5",
                    "visitor_id": visitor_id,
                    "event_type": "BILLING_COMPLETED",
                    "timestamp": converted_time.isoformat().replace("+00:00", "Z"),
                    "zone_id": "BILLING",
                    "dwell_ms": 0,
                    "is_staff": False,
                    "confidence": 0.99,
                    "metadata": {
                        "customer_name": customer_name,
                        "transaction_id": row.get("order_id", ""),
                        "session_seq": 5,
                        "store_section": "Billing"
                    }
                })
                
            except Exception as e:
                print(f"Error processing row: {e}")
                continue
    
    print(f"Generated {len(events)} events from {len(customer_visits)} unique customer visits")
    return events


def main():
    """Generate and save events to JSON file."""
    root = Path(__file__).parent.parent
    output_file = root / "data" / "store_events.jsonl"
    
    events = generate_events_from_pos()
    
    # Write events to JSONL file
    with open(output_file, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
    
    print(f"Wrote {len(events)} events to {output_file}")


if __name__ == "__main__":
    main()
