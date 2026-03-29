"""Integration-style API smoke tests using FastAPI TestClient."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from main import app


def _pretty(obj) -> str:
    """Render dict/list as pretty JSON for console output."""

    return json.dumps(obj, indent=2, sort_keys=True, default=str)


def main() -> None:
    """Run a simple API flow test against local FastAPI app object."""

    all_ok = True
    client = TestClient(app)

    # 1) GET /health
    r = client.get("/health")
    print("--- GET /health ---")
    print(_pretty(r.json()))
    if r.status_code != 200 or r.json().get("status") != "ok":
        all_ok = False

    # 2) GET /watchlist
    r = client.get("/watchlist")
    print("\n--- GET /watchlist ---")
    print(_pretty(r.json()))
    if r.status_code != 200 or "symbols" not in r.json():
        all_ok = False

    # 3) POST /run-analysis
    r = client.post("/run-analysis", json={"user_id": "sai_aditya"})
    print("\n--- POST /run-analysis ---")
    print(_pretty(r.json()))
    if r.status_code != 200:
        all_ok = False

    # 4) GET /recommendations/today
    r = client.get("/recommendations/today")
    print("\n--- GET /recommendations/today ---")
    print(_pretty(r.json()))
    if r.status_code != 200:
        all_ok = False

    # 5) GET /recommendations/winrate
    r = client.get("/recommendations/winrate")
    print("\n--- GET /recommendations/winrate ---")
    print(_pretty(r.json()))
    if r.status_code != 200:
        all_ok = False

    if all_ok:
        print("\n✅ FastAPI test complete")
    else:
        print("\n⚠️ FastAPI test completed with one or more failures.")


if __name__ == "__main__":
    main()

