# Project: ytmusic-sync

## Overview
A standalone Python utility that scrapes Spotify Weekly charts directly from Kworb (Global and India charts only), resolves track IDs using YouTube Music API, caches the metadata locally, and synchronizes them into public/private YouTube Music playlists.

## Structure
ytmusic-sync/
├── .github/
│   └── workflows/
│       └── sync.yml   # GitHub Actions workflow for scheduled daily sync using uv
├── data/              # Cached country charts and resolved ytMusicId entries
├── auth.py            # Interactive script to set up browser authentication credentials
├── utils.py           # Common constants and shared generic utilities
├── scraper.py         # Parsing and HTML scraping logic for Kworb weekly charts
├── playlist_sync.py   # YouTube Music library operations and cache checks
├── sync.py            # Orchestrator and entry point CLI script
├── test_sync.py       # Offline unit tests for utility and parsing logic
├── requirements.txt   # Project dependencies (ytmusicapi, requests, beautifulsoup4)
├── browser.json       # Generated browser credentials (must be kept out of version control)
└── README.md          # User setup and execution documentation

## Conventions
- Use `uv` for python dependency management.
- Sync playlists using the safe add-then-remove flow to avoid empty-playlist states, keeping sequential resolution for cache safety.

## Dependencies & Setup
- `ytmusicapi>=1.12.1`
- `requests` and `beautifulsoup4` for web scraping.

## Critical Information
- Do not commit `browser.json` or the `data/` cache folder to version control (configured in `.gitignore`).
- YouTube's OAuth implementation for `ytmusicapi` is currently experiencing a backend issue (Issue #813) returning `400 Bad Request` on authenticated endpoints. Browser headers (`browser.json`) is the recommended working authentication method.

## Insights
- Cache loaded from existing JSONs in `data/` prevents duplicate YouTube Music searches and speeds up subsequent runs.

## Blunders
- [2026-07-01] YouTube Music search and library endpoints fail with 400 Bad Request when authenticated with OAuth client credentials. → YouTube changed backend APIs breaking OAuth clients in ytmusicapi. → Fixed by switching automated synchronization to use Browser Cookie authentication (`browser.json`) instead of OAuth, and routing searches through the authenticated client to avoid unauthenticated rate-limiting.
- [2026-07-01] YTM API `add_playlist_items` returns `STATUS_FAILED` and rejects the entire 50-track chunk if the list contains any duplicate video IDs. → Fixed by stable-deduplicating track IDs in `sync.py` before batching and uploading.
- [2026-07-01] `create_playlist` fails with `"STATUS_FAILED"` string response instead of raising an exception, bypassing retry logic. → Fixed by raising a `RuntimeError` on failure to trigger `retry_operation`.
- [2026-07-01] YTM API `add_playlist_items` returns `STATUS_FAILED` with a "Duplicates" dialog warning when adding new tracks that already exist in the playlist (safe add-then-remove flow). → Fixed by passing `duplicates=True` to `add_playlist_items` to allow appending duplicate tracks before removing the old instances.
- [2026-07-01] Similarity matching rejected 25/200 tracks because YTM appends `(feat. ...)`, `(Radio Edit)`, `(Explicit Ver.)`, `- 2012 Remaster` etc. to titles. → Fixed by adding `clean_title()` that strips featured artists, version/remaster/edit suffixes, and explicit/clean tags before comparison. Also added `unicodedata.normalize('NFKD')` to `clean_string()` to handle accented characters (e.g. eńau, JAŸ-Z).
- [2026-07-01] Kworb HTML scraper produces mojibake artist names (e.g. `JAÅ¸-Z` instead of `JAŸ-Z`) because `requests` auto-detects encoding incorrectly. → Fixed by forcing `res.encoding = "utf-8"` in `scraper.py` before accessing `res.text`.
- [2026-07-01] Some tracks (e.g. Drake "One Dance") don't appear in YTM `filter="songs"` results but exist as music videos. → Added video search fallback in `resolve_track_ids`: if songs search fails, retries with `filter="videos"` using the same 0.80 threshold.
- [2026-07-02] Over-engineered search matching with 6 artist fallback layers led to false-positive rejections for Bollywood tracks. → Replaced with primary title matching (similarity ratio >= 0.85) with artist matching as a preference/tiebreak candidate.
- [2026-07-02] Swapped difflib for rapidfuzz.fuzz.WRatio for title similarity (threshold 85) and tightened artist_matches using fuzz.token_set_ratio to prevent false-positives from simple substring containment (e.g., "Ana" vs "Anastasia").
- [2026-07-02] `clean_title()` stripped the ordinary word "with" anywhere in un-bracketed titles. → Fixed by removing "with" from the un-delimited regex.
- [2026-07-02] `remove_playlist_items()` was sent all items at once, exceeding the YTM API limit of 50. → Fixed by chunking playlist removals in batches of 50.
- [2026-07-02] Tracks with a single anchor tag on Kworb had empty artists. → Fixed by parsing raw text inside the td and splitting by `" - "` to extract the artist.
- [2026-07-02] `auth.py` was calling `YTMusic.setup()` which is no longer a method on the `YTMusic` class in newer `ytmusicapi` versions. → Fixed by importing and calling the module-level `setup` function.
