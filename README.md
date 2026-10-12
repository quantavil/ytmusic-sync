# 🎵 Spotify to YouTube Music Sync Bot

[![Python](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![Package Manager](https://img.shields.io/badge/managed%20by-uv-purple.svg)](https://github.com/astral-sh/uv)
[![API](https://img.shields.io/badge/YouTube%20Data%20API-v3-red.svg)](https://developers.google.com/youtube/v3)
[![CI](https://img.shields.io/badge/GitHub%20Actions-scheduled-green.svg)](https://github.com/quantavil/ytmusic-sync/actions)
[![Spotify](https://img.shields.io/badge/Spotify-Charts-1ED760?logo=spotify&logoColor=white)](https://kworb.net/spotify/)
[![YouTube Music](https://img.shields.io/badge/YouTube-Music-FF0000?logo=youtubemusic&logoColor=white)](https://music.youtube.com/)

A lightweight, autonomous Python utility that automatically synchronizes **Spotify Weekly Top 200 Charts** directly into YouTube Music playlists. It scrapes charts from Kworb, resolves tracks to YouTube Music video IDs with local caching, and reconciles playlists using a quota-optimal single-pass LIS algorithm.

---

## 🎧 Live YouTube Music Playlists

Click below to open and listen directly to the live synchronized playlists:

| Chart | YouTube Music Playlist | Direct Streaming Link | Update Schedule (07:30 UTC / 1:00 PM IST) |
| :--- | :--- | :--- | :--- |
| 🌍 **Global** | **Spotify Weekly Global Top 200** | [▶️ **Listen on YouTube Music**](https://music.youtube.com/playlist?list=PLN7oNg7bR2bo) <br><sub>[Standard YouTube Link](https://www.youtube.com/playlist?list=PLN7oNg7bR2bo)</sub> | **Saturday** ([`sync-global.yml`](.github/workflows/sync-global.yml)) |
| 🇮🇳 **India** | **Spotify Weekly India Top 200** | [▶️ **Listen on YouTube Music**](https://music.youtube.com/playlist?list=PLZKHuuLG3Vpo) <br><sub>[Standard YouTube Link](https://www.youtube.com/playlist?list=PLZKHuuLG3Vpo)</sub> | **Sunday** ([`sync-india.yml`](.github/workflows/sync-india.yml)) |
| 🇺🇸 **United States** | **Spotify Weekly United States Top 200** | *Auto-created on first sync* | **Monday & Thursday** ([`sync-us.yml`](.github/workflows/sync-us.yml)) |
| 📻 **Radio** | **Billboard Radio Songs Top 100** | *Auto-created on first sync* | **Tuesday** ([`sync-radio.yml`](.github/workflows/sync-radio.yml)) |
| 🍎 **Apple Music** | **Apple Music Top 200 - Worldwide** | *Auto-created on first sync* | **Wednesday & Friday** ([`sync-apple.yml`](.github/workflows/sync-apple.yml)) |

> [!NOTE]
> Workflows run on dedicated days to guarantee that each chart sync has access to the full **10,000 daily YouTube Data API quota units** without contention. Thursday and Friday serve as automated resume days for 200-track cold starts and heavy turnover weeks.

---

## ⚡ Quickstart

### 1. Install Dependencies
This project uses [`uv`](https://github.com/astral-sh/uv) for fast package management:
```bash
uv pip install -r requirements.txt --python .venv
```

### 2. Configure Google OAuth
Playlist modifications require the official YouTube Data API v3:

1. In [Google Cloud Console](https://console.cloud.google.com/), enable **YouTube Data API v3**.
2. Configure OAuth Consent Screen (*External* -> *In Production* so credentials remain active).
3. Create an **OAuth Client ID** (Desktop Application) and download as `client_secrets.json`.
4. Generate your authentication token:
   ```bash
   uv run python auth_google.py
   ```
   Follow the browser login prompt. This creates a secure, auto-refreshing `token.json`.

### 3. Run the Sync
```bash
# Sync Global Spotify Top 200
uv run python sync.py --country global

# Sync India Spotify Top 200
uv run python sync.py --country in

# Sync US Spotify Top 200
uv run python sync.py --country us

# Sync Billboard Radio Top 100
uv run python sync.py --country radio

# Sync Worldwide Apple Music Top 200
uv run python sync.py --country apple_songs

# Dry run (test scraping and track resolution without mutating playlists)
uv run python sync.py --country us --dry-run
```

*(Linux shortcut: Run `./sync.sh` to sync charts sequentially or `./sync.sh radio` for an individual chart).*

---

## 🎯 Quota Optimization & Architecture

The YouTube Data API provides **10,000 units/day** (each track insert/move/delete costs 50 units, allowing ~200 writes/day). The bot maximizes this budget via:

- **Free Search Enrichment:** Track search and resolution use unauthenticated `ytmusicapi` (consuming 0 official Data API quota).
- **Metadata Caching:** Resolved IDs are saved under `data/`, making repeat track lookups instantaneous.
- **Single-Pass LIS Reconciliation:** The bot determines the *Longest Increasing Subsequence* of already-ordered tracks and only repositions misplaced songs once.
- **Resumable / Self-Healing:** If quota runs out mid-sync, the run marks the cache with `-partial`. The next scheduled run reads the live playlist state and seamlessly finishes the remaining tracks.

---

## ⚙️ CLI Options

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--country` | Target chart to sync (`global` or `in`). | `global` |
| `--dry-run` | Simulate actions without modifying YouTube Music. | `False` |
| `--force` | Force sync even if week date has not changed. | `False` |
| `--min-resolve-ratio` | Minimum track resolution ratio before mutating (default: 90%). | `0.90` |
| `--data-dir` | Path to store local JSON chart caches. | `data` |
| `--auth` | Path to Google OAuth token file. | `token.json` |

---

## 🤖 GitHub Actions Automation

Automated runs execute via GitHub Actions:

1. Copy the contents of your local `token.json`.
2. In your repository, go to **Settings** > **Secrets and variables** > **Actions** > **New repository secret**.
3. Create secret **`YT_OAUTH_TOKEN_JSON`** and paste the JSON contents.
4. Each workflow (`sync-global.yml` and `sync-india.yml`) restores the token, resolves tracks, updates playlists, and caches metadata across runs.

---

## 🏷️ Tags & Topics

`#spotify` `#youtube-music` `#ytmusic` `#spotify-charts` `#kworb` `#playlist-sync` `#music-sync` `#spotify-top-200` `#india-top-200` `#global-top-200` `#automation` `#github-actions` `#python`
