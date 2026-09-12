import os
from pathlib import Path

import httpx
import msal

SCOPES = ["Calendars.ReadWrite", "Contacts.ReadWrite"]
_AUTHORITY = "https://login.microsoftonline.com/common"
_GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _cache_path() -> Path:
    return Path(os.environ.get("GRAPH_TOKEN_CACHE_PATH", ".graph_token_cache.json"))


def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    path = _cache_path()
    if path.exists():
        cache.deserialize(path.read_text())
    return cache


def _save_cache(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        _cache_path().write_text(cache.serialize())


def _get_app(cache: msal.SerializableTokenCache) -> msal.PublicClientApplication:
    return msal.PublicClientApplication(
        os.environ["GRAPH_CLIENT_ID"], authority=_AUTHORITY, token_cache=cache
    )


def device_code_login() -> dict:
    """One-time interactive sign-in. Run manually (needs a browser somewhere,
    not necessarily this machine) via server/services/graph_auth_setup.py.
    Persists tokens (including the refresh token) to the local cache file;
    every subsequent get_access_token() call redeems/rotates it silently.
    """
    cache = _load_cache()
    app = _get_app(cache)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(f"failed to start device flow: {flow}")
    print(flow["message"])
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(f"device code sign-in failed: {result.get('error_description')}")
    _save_cache(cache)
    return result


def get_access_token() -> str:
    cache = _load_cache()
    app = _get_app(cache)
    accounts = app.get_accounts()
    if not accounts:
        raise RuntimeError(
            "no signed-in Graph account -- run `uv run python server/services/graph_auth_setup.py` once"
        )
    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    if not result or "access_token" not in result:
        raise RuntimeError(
            "Graph token refresh failed -- re-run `uv run python server/services/graph_auth_setup.py`"
        )
    _save_cache(cache)
    return result["access_token"]


def graph_request(method: str, path: str, **kwargs) -> dict:
    """path is relative to the v1.0 base, e.g. '/me/events'."""
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {get_access_token()}"
    response = httpx.request(method, f"{_GRAPH_BASE}{path}", headers=headers, timeout=30.0, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else {}
