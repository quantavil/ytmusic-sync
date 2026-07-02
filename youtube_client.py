"""
Wrapper around the official YouTube Data API v3 client.

Handles:
  - loading + auto-refreshing credentials from token.json
  - a call() helper that classifies HttpError responses and reacts
    appropriately instead of blindly retrying everything the same way:
      * 403 quotaExceeded / dailyLimitExceeded -> abort immediately,
        retrying just burns more time for a guaranteed-same failure
      * 401 / invalid_grant                    -> clear re-auth message
      * 429 / 5xx / network errors             -> retry with backoff
      * anything else                          -> raise immediately
"""
import sys
import time
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

TOKEN_FILE = "token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube"]


class QuotaExceededError(RuntimeError):
    """Raised when the daily YouTube Data API quota is exhausted. Not retryable today."""
    pass


class AuthError(RuntimeError):
    """Raised when token.json is missing/invalid/revoked and needs auth_google.py re-run."""
    pass


def get_youtube_client(token_path=None):
    token_path = Path(token_path or TOKEN_FILE)
    if not token_path.exists():
        raise AuthError(f"Credentials token file '{token_path}' not found.")

    try:
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    except Exception as e:
        raise AuthError(f"Failed to load {token_path}: {e}")

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # access_token was refreshed; refresh_token itself is unchanged
            # in almost all cases, but persist anyway in case Google rotated it.
            token_path.write_text(creds.to_json(), encoding="utf-8")
        except Exception as e:
            raise AuthError(
                f"Failed to refresh credentials: {e}. "
                f"The refresh token may have been revoked — re-run auth_google.py."
            )
    elif not creds.valid:
        raise AuthError("token.json has no valid/refreshable credentials — re-run auth_google.py.")

    return build("youtube", "v3", credentials=creds, static_discovery=True)


def _classify_http_error(e: HttpError):
    status = e.resp.status if getattr(e, "resp", None) else None
    reason_str = str(e).lower()

    if status == 403 and ("quotaexceeded" in reason_str or "dailylimitexceeded" in reason_str or "ratelimitexceeded" in reason_str):
        return "quota"
    if status in (401,) or "invalid_grant" in reason_str or "unauthorized" in reason_str:
        return "auth"
    if status in (429, 500, 502, 503, 504):
        return "transient"
    return "fatal"


def call(func, attempts=3, delay=2, error_msg="YouTube API call"):
    """
    Executes func() (a zero-arg callable wrapping a googleapiclient .execute()
    call) with classification-aware retry.
    """
    for attempt in range(attempts):
        try:
            return func()
        except HttpError as e:
            kind = _classify_http_error(e)
            if kind == "quota":
                raise QuotaExceededError(
                    f"{error_msg}: YouTube Data API daily quota exceeded. "
                    f"Not retrying — quota resets at midnight Pacific Time. ({e})"
                )
            if kind == "auth":
                raise AuthError(f"{error_msg}: authorization error, re-run auth_google.py. ({e})")
            if kind == "transient" and attempt < attempts - 1:
                wait = delay * (attempt + 1)
                print(f"  ⚠ {error_msg} (attempt {attempt + 1}/{attempts}) transient error: {e}. Retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise
        except RefreshError as e:
            raise AuthError(f"{error_msg}: credentials refresh failed: {e}. Re-run auth_google.py.")
        except Exception as e:
            # Network-level errors etc. — treat as transient.
            if attempt < attempts - 1:
                wait = delay * (attempt + 1)
                print(f"  ⚠ {error_msg} (attempt {attempt + 1}/{attempts}) failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise