from __future__ import annotations

import argparse
import asyncio
import time

import httpx
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table


def build_table(store_id: str, metrics: dict, funnel: dict, health: dict) -> Table:
    table = Table(title=f"Live Store Intelligence — {store_id}", expand=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Unique Visitors", str(metrics.get("unique_visitors", 0)))
    table.add_row("Conversion Rate", f"{metrics.get('conversion_rate', 0) * 100:.2f}%")
    table.add_row("Queue Depth", str(metrics.get("queue_depth", 0)))
    table.add_row("Abandonment Rate", f"{metrics.get('abandonment_rate', 0) * 100:.2f}%")
    for stage in funnel.get("stages", []):
        table.add_row(f"Funnel · {stage['stage']}", str(stage["count"]))
    table.add_row("API Health", health.get("status", "UNKNOWN"))
    if health.get("warnings"):
        table.add_row("Warnings", ", ".join(health["warnings"]))
    return table


async def poll(api_url: str, store_id: str, interval: float) -> None:
    console = Console()
    async with httpx.AsyncClient(base_url=api_url, timeout=10.0) as client:
        with Live(console=console, refresh_per_second=4) as live:
            while True:
                metrics = (await client.get(f"/stores/{store_id}/metrics")).json()
                funnel = (await client.get(f"/stores/{store_id}/funnel")).json()
                health = (await client.get("/health")).json()
                table = build_table(store_id, metrics, funnel, health)
                live.update(Panel(table, subtitle=f"Updated every {interval}s"))
                await asyncio.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--store-id", default="STORE_BLR_002")
    parser.add_argument("--interval", type=float, default=3.0)
    args = parser.parse_args()
    asyncio.run(poll(args.api_url, args.store_id, args.interval))


if __name__ == "__main__":
    main()
