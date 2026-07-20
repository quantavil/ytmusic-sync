# 🎵 Spotify to YouTube Music Playlist Sync Bot

A lightweight, standalone Python utility that scrapes **Spotify Weekly Charts** directly from Kworb, resolves the track IDs to YouTube Music video IDs (with local metadata caching), and automatically synchronizes them into public YouTube Music playlists.

---

## 📋 Playlists Created on YouTube Music

The bot will search for or create the following playlists in your YouTube Music library:

| Chart | YouTube Music Playlist Name | Description |
| :--- | :--- | :--- |
| **Global** | `Spotify Weekly Global Top 200` | Synced from Spotify Weekly Global Chart. |
| **India** | `Spotify Weekly India Top 200` | Synced from Spotify Weekly India Chart. |

> [!NOTE]
> If a playlist with the exact target title already exists in your library, the bot will reuse it. Otherwise, it will create a new public playlist.
>
> During sync, the bot reconciles the existing playlist against the latest chart in a **single left-to-right pass**: new tracks are inserted, out-of-order tracks are repositioned at most once, and dropped tracks are removed last. Tracks that are already in the correct relative order (the Longest Increasing Subsequence) are left untouched, so the number of quota-costing operations is kept to the minimum.

---

## 🛠️ Setup & Installation

This directory is managed using `uv` (a fast Python package installer and resolver).

### 1. Initialize Virtual Environment & Install Dependencies
From the root of this directory (`ytmusic-sync`), run:
```bash
# Verify venv is created and packages are installed
uv pip install -r requirements.txt --python .venv
```

### 2. Configure Authentication
To write and update playlists in your YouTube Music library, you must authenticate using the official Google YouTube Data API v3.

1. **Google Cloud Console Setup:**
   - Go to [Google Cloud Console](https://console.cloud.google.com/) and create/select a project.
   - Enable **YouTube Data API v3** in APIs & Services > Library.
   - Configure the **OAuth Consent Screen** (User type "External", publish the app "In production" so credentials don't expire in 7 days).
   - Go to **Credentials**, create an **OAuth client ID** of type **Desktop app**, and download the client secrets JSON.
   - Save the downloaded file as `client_secrets.json` in the root of this directory.

2. **Generate Token:**
   Run the setup script using either of the following commands:
   ```bash
   uv run python3 auth_google.py
   # OR
   .venv/bin/python auth_google.py
   ```
   Follow the on-screen instructions to log into your Google Account in the browser and grant the requested permissions. This generates `token.json`.

---

## 🚀 Running the Sync

Once authentication is configured (having `token.json` in this directory), run the sync script using either the `uv` tool or the direct virtual environment interpreter:

### Sync Spotify Global Chart
```bash
uv run python3 sync.py --country global
# OR
.venv/bin/python sync.py --country global
```

### Sync Spotify India Chart
```bash
uv run python3 sync.py --country in
# OR
.venv/bin/python sync.py --country in
```

### Dry Run (Test without mutating playlists)
```bash
uv run python3 sync.py --country global --dry-run
# OR
.venv/bin/python sync.py --country global --dry-run
```

> [!IMPORTANT]
> **YouTube API Quota Limits:** YouTube Data API v3 has a default daily project quota of 10,000 units, and each playlist item insert/update/delete costs 50 units — so a single day allows only ~200 mutations. The sync minimizes mutations (single-pass reconciliation, LIS-anchored tracks are never moved), which keeps a typical 200-track reshuffle comfortably under the daily budget. On a very first cold-start sync against a badly-ordered playlist you may still approach the ceiling; if you hit a `QuotaExceededError`, the run saves its resolved-ID cache as `-partial` and the next day's run resumes where it left off. Running both Global and India on a fresh setup can exceed the budget in one day — space them out or request a quota increase in Google Cloud Console. Once cached under `data/`, subsequent weekly runs only apply the delta and use minimal quota.

### 🔁 Self-Healing & Resumable Syncs

If a run is interrupted partway through — most commonly by a `QuotaExceededError` on a cold start — **it recovers automatically on the next run**. No manual cleanup, no corrupted playlist.

This works because every run is *stateless about prior runs*: it fetches the **current live playlist**, recomputes the delta against the target chart from scratch, and applies only what's missing. Three mechanisms make resumption reliable:

| Mechanism | Effect |
| :--- | :--- |
| `-partial` weekDate marker | An interrupted run tags its cache as `…-partial`, so the next run does **not** skip it as "already done". |
| Fresh playlist re-fetch | The next run reads the partially-modified playlist as its new starting point. |
| Preserved resolved-ID cache | Track resolution is near-free on subsequent runs, so the full quota goes toward playlist mutations. |

Convergence is **monotonic**: each run inserts missing tracks, repositions misplaced ones (at most once), and removes stale/duplicate ones — and running against an already-synced playlist performs **zero** operations (idempotent). So a cold start simply finishes over the next 1–2 days, and steady weekly runs complete same-day.

> [!NOTE]
> Verified by a 300-trial randomized simulation under a brutal 1–4 mutations/day cap (aborting mid-run every day): the playlist converged to the **exact** target every time. Resumption assumes the target chart is stable between runs, which holds since Kworb refreshes the weekly chart only once a week.

### ⚡ One-Click Local Sync (Linux)
You can synchronize both Global and India charts sequentially in a single step using the provided helper shell script:
```bash
./sync.sh
```
Alternatively, double-click `sync.sh` in your graphical file manager and select **"Run in Terminal"**.

---

## ⚙️ Command-Line Options

| Argument | Description | Default |
| :--- | :--- | :--- |
| `--country` | Country code of the chart to sync (`global` or `in`). | `global` |
| `--data-dir` | Path to save/load scraped JSON cache metadata. | `data` |
| `--auth` | Specific path to the Google OAuth token file. | *Auto-detects `token.json`* |
| `--dry-run` | Run the sync logic and output actions without writing to YouTube Music. | *Disabled* |
| `--force` | Force sync even if the weekDate has not changed. | *Disabled* |

---

## 🤖 GitHub Actions Automation

The repository includes a GitHub Actions workflow `.github/workflows/sync.yml` to automatically run the sync daily at **`07:30 UTC`** (1:00 PM IST).

### Configuration Steps:
1. Copy the contents of your locally generated `token.json`.
2. Go to your GitHub repository -> **Settings** -> **Secrets and variables** -> **Actions** -> **New repository secret**.
3. Create a secret named **`YT_OAUTH_TOKEN_JSON`** and paste the JSON contents.
4. Push the code to your GitHub repository:
   ```bash
   git init
   git add .
   git commit -m "feat: initial commit standalone scraper and sync bot"
   git branch -M main
   git remote add origin https://github.com/quantavil/ytmusic-sync.git
   git push -u origin main
   ```
