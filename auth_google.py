#!/usr/bin/env python3
"""
One-time local setup for official YouTube Data API v3 access.

Generates token.json, which sync.py uses for all playlist mutations
(create/read/update/delete). Unlike browser.json cookies, this never
needs to be regenerated as long as:
  - the OAuth consent screen is published ("In production"), and
  - the token is used at least once every 6 months, and
  - you don't revoke access from your Google Account.

Setup (one-time, before running this script):
  1. Go to https://console.cloud.google.com/ and create (or select) a project.
  2. Enable "YouTube Data API v3" under APIs & Services > Library.
  3. Configure the OAuth consent screen (APIs & Services > OAuth consent
     screen): User type "External", add yourself as a test user is fine
     to start, but PUBLISH the app ("In production") before relying on
     this for automation — testing-mode refresh tokens expire in 7 days.
     Personal-use apps with <100 users don't need full verification;
     you'll just see an "unverified app" warning once below — that's
     expected, click through it.
  4. Create credentials: APIs & Services > Credentials > Create Credentials
     > OAuth client ID > Application type "Desktop app". Download the JSON
     and save it as client_secrets.json in this directory.
  5. Run this script.
"""
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Minimal scope: only playlist read/write, nothing else.
SCOPES = ["https://www.googleapis.com/auth/youtube"]

CLIENT_SECRETS_FILE = "client_secrets.json"
TOKEN_FILE = "token.json"


def main():
    print("====================================================")
    print("   YouTube Data API v3 — Official OAuth Setup        ")
    print("====================================================\n")

    secrets_path = Path(CLIENT_SECRETS_FILE)
    if not secrets_path.exists():
        print(f"❌ Error: {CLIENT_SECRETS_FILE} not found in this directory.")
        print("Download it from Google Cloud Console > APIs & Services > Credentials")
        print("(OAuth client ID, type 'Desktop app') and save it here first.")
        print("See the docstring at the top of this file for the full one-time setup steps.")
        sys.exit(1)

    print("A browser window will open for you to sign in and grant access.")
    print("You may see an 'unverified app' warning — that's expected for a personal")
    print("project. Click 'Advanced' > 'Go to (app name) (unsafe)' to proceed.\n")
    input("Press [Enter] to continue...")

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
        # access_type=offline (default for InstalledAppFlow) + prompt=consent
        # ensures a refresh_token is actually issued even on repeat auth.
        creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    except Exception as e:
        print(f"\n❌ Error during OAuth flow: {e}")
        sys.exit(1)

    Path(TOKEN_FILE).write_text(creds.to_json(), encoding="utf-8")
    print(f"\n🎉 Success! Saved credentials to {TOKEN_FILE}.")
    print("Keep this file secret — treat it like a password.")
    print("For GitHub Actions, copy its contents into a repo secret named YT_OAUTH_TOKEN_JSON.")

    # Sanity check: make sure it actually refreshes.
    print("\nVerifying token can be refreshed...")
    creds.refresh(Request())
    print("✅ Token refresh verified. You're set up.")


if __name__ == "__main__":
    main()