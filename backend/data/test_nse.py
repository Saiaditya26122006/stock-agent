"""Runtime checks for NSE public API ingestion module."""

from __future__ import annotations

from data.nse import (
    get_circuit_filter_status,
    get_fii_dii_data,
    get_fo_pcr,
    get_full_premarket_data,
    get_gift_nifty,
    get_india_vix_nse,
    get_nse_announcements,
)


def _print_result(name: str, passed: bool, detail: str) -> None:
    print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")


def run_tests() -> None:
    # 1) VIX
    vix = get_india_vix_nse()
    _print_result(
        "get_india_vix_nse",
        isinstance(vix, dict) and float(vix.get("vix", 0.0)) > 0.0,
        f"vix={vix.get('vix')} regime={vix.get('regime')}",
    )

    # 2) FII/DII
    fii_dii = get_fii_dii_data()
    _print_result(
        "get_fii_dii_data",
        isinstance(fii_dii, dict),
        f"fii_net={fii_dii.get('fii_net')} mood={fii_dii.get('fii_mood')}",
    )

    # 3) Circuit filter
    circuit = get_circuit_filter_status("RELIANCE")
    _print_result(
        "get_circuit_filter_status(RELIANCE)",
        isinstance(circuit, dict) and circuit.get("symbol") == "RELIANCE",
        str(circuit),
    )

    # 4) Announcements
    ann = get_nse_announcements("TCS")
    _print_result(
        "get_nse_announcements(TCS)",
        isinstance(ann, list),
        f"count={len(ann)}",
    )

    # 5) PCR
    pcr = get_fo_pcr("TCS")
    _print_result(
        "get_fo_pcr(TCS)",
        isinstance(pcr, dict),
        f"pcr={pcr.get('pcr')} signal={pcr.get('pcr_signal')}",
    )

    # 6) Gift Nifty
    gift = get_gift_nifty()
    _print_result(
        "get_gift_nifty",
        isinstance(gift, dict),
        f"gift={gift.get('gift_nifty')} bias={gift.get('bias')}",
    )

    # 7) Full premarket
    full = get_full_premarket_data(["RELIANCE", "TCS"])
    required = {"vix", "fii_dii", "gift_nifty", "circuit_filters", "announcements", "fo_pcr", "timestamp"}
    _print_result(
        "get_full_premarket_data",
        isinstance(full, dict) and required.issubset(set(full.keys())),
        f"keys_present={sorted(list(full.keys()))}",
    )


if __name__ == "__main__":
    run_tests()
