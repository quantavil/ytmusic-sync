# Project: ytmusic-sync

## Overview
A standalone Python utility that scrapes Spotify Weekly charts directly from Kworb (Global and India charts only), resolves track IDs using YouTube Music API, caches the metadata locally, and synchronizes them into public/private YouTube Music playlists.

## Structure
ytmusic-sync/
├── .github/
│   └── workflows/
│       └── sync.yml   # GitHub Actions workflow for scheduled daily sync using uv
├── data/              # Cached country charts and resolved ytMusicId entries
├── auth.py            # Interactive script to set up credentials (supports Browser headers and OAuth)
├── sync.py            # Standalone scraping and playlist synchronization script
├── requirements.txt   # Project dependencies (ytmusicapi, requests, beautifulsoup4)
├── browser.json       # Generated browser credentials (must be kept out of version control)
└── README.md          # User setup and execution documentation

## Conventions
- Use `uv` for python dependency management.
- Rebuild playlists by removing all existing tracks and adding the newly scraped track IDs.

## Dependencies & Setup
- `ytmusicapi>=1.12.1`
- `requests` and `beautifulsoup4` for web scraping.

## Critical Information
- Do not commit `browser.json` or the `data/` cache folder to version control (configured in `.gitignore`).
- YouTube's OAuth implementation for `ytmusicapi` is currently experiencing a backend issue (Issue #813) returning `400 Bad Request` on authenticated endpoints. Browser headers (`browser.json`) is the recommended working authentication method.

## Insights
- Public operations (like `search`) do not require authentication and can be performed using an unauthenticated `YTMusic()` instance to bypass OAuth-related 400 Bad Request errors.
- Cache loaded from existing JSONs in `data/` prevents duplicate YouTube Music searches and speeds up subsequent runs.

## Blunders
- [2026-07-01] YouTube Music search and library endpoints fail with 400 Bad Request when authenticated with OAuth client credentials. → YouTube changed backend APIs breaking OAuth clients in ytmusicapi. → Fixed by routing searches through a separate unauthenticated `YTMusic()` instance, and switching automated synchronization to use Browser Cookie authentication (`browser.json`) instead of OAuth.
