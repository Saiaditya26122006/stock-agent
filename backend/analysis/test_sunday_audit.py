"""
Manual test runner for Sunday audit.

Run from backend/:
    python -m analysis.test_sunday_audit
"""

from __future__ import annotations

from pprint import pprint


def main() -> None:
    try:
        from analysis.sunday_audit import run_sunday_audit

        result = run_sunday_audit(user_id="sai_aditya")
        print("\nSunday Audit Result\n" + "-" * 22)
        pprint(result.to_dict(), sort_dicts=False)
    except Exception as exc:
        print(f"test_sunday_audit failed: {exc}")


if __name__ == "__main__":
    main()

