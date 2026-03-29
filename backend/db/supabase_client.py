"""
Shared Supabase client for the backend.

Reads credentials from backend/.env and exposes a single `supabase_client`
instance for all database modules to use.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from supabase import Client, create_client


logger = logging.getLogger(__name__)

_SUPABASE_CLIENT: Optional[Client] = None


def _load_env() -> None:
    """Load environment variables from backend/.env if present."""

    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)


def _create_supabase_client() -> Client:
    """
    Internal helper to create a Supabase client using the service key.

    Uses SUPABASE_URL and SUPABASE_SERVICE_KEY from environment variables.
    """

    _load_env()
    url = os.getenv("SUPABASE_URL", "").strip()
    service_key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    if not url or not service_key:
        raise RuntimeError(
            "Supabase credentials missing: ensure SUPABASE_URL and "
            "SUPABASE_SERVICE_KEY are set in backend/.env"
        )
    return create_client(url, service_key)


def get_supabase_client() -> Client:
    """
    Return the singleton Supabase client instance.

    This ensures only one client is created and reused across the app.
    """

    global _SUPABASE_CLIENT
    if _SUPABASE_CLIENT is None:
        _SUPABASE_CLIENT = _create_supabase_client()
    return _SUPABASE_CLIENT


# Eagerly create a shared client for convenient imports.
supabase_client: Client = get_supabase_client()


def test_connection() -> bool:
    """
    Perform a light connectivity check against the `user_config` table.

    Returns:
        True if a simple SELECT completes successfully, False otherwise.
    """

    try:
        client = get_supabase_client()
        resp = client.table("user_config").select("user_id").limit(1).execute()
        error = getattr(resp, "error", None)
        if error:
            logger.error("Supabase test_connection error: %s", error)
            return False
        # If we can access .data without errors, we assume the connection is OK.
        _ = getattr(resp, "data", None)
        logger.info("Supabase test_connection succeeded.")
        return True
    except Exception as exc:
        logger.error("Supabase test_connection failed: %s", exc)
        return False

