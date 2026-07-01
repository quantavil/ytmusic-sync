#!/usr/bin/env python3
import json
import argparse
import sys
import re
import time
import random
from pathlib import Path
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup
from ytmusicapi import YTMusic

# Supported countries (Global and India only)
COUNTRIES = {
    "global": {"name": "Global", "slug": "global_weekly"},
    "in": {"name": "India", "slug": "in_weekly"}
}

BASE_URL = "https://kworb.net/spotify/country"

def parse_args():
    parser = argparse.ArgumentParser(description="Sync Spotify charts to YouTube Music playlists.")
    parser.add_argument(
        "--country",
        type=str,
        default="global",
        choices=list(COUNTRIES.keys()),
        help="Country chart to sync ('global' or 'in')."
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data",
        help="Path to save/load scraped JSON data."
    )
    parser.add_argument(
        "--auth",
        type=str,
        default=None,
        help="Path to auth file (browser.json). Auto-detects if omitted."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without modifying YouTube Music playlists."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force sync even if the weekDate has not changed."
    )
    return parser.parse_args()

def extract_week_date(soup):
    sources = []
    pagetitle_span = soup.find("span", class_="pagetitle")
    if pagetitle_span:
        sources.append(pagetitle_span.get_text())
    if soup.title:
        sources.append(soup.title.get_text())
    
    for s in sources:
        m = re.search(r"(\d{4})[-/](\d{2})[-/](\d{2})", s)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        m2 = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", s)
        if m2:
            try:
                date_str = f"{m2.group(1)} {m2.group(2)} {m2.group(3)}".replace(",", "")
                for fmt in ("%B %d %Y", "%b %d %Y"):
                    try:
                        return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
                    except ValueError:
                        continue
            except Exception:
                pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def parse_num(raw):
    raw_clean = re.sub(r"[^\d]", "", raw)
    return int(raw_clean) if raw_clean else 0

def scrape_kworb(country_code):
    country_config = COUNTRIES[country_code]
    url = f"{BASE_URL}/{country_config['slug']}.html"
    print(f"⏳ Scraping Kworb Weekly Chart: {url} ...")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MusicChartsDash/1.0)"}
    
    # Fetch HTML with simple retry mechanism
    for attempt in range(3):
        try:
            res = requests.get(url, headers=headers, timeout=15)
            res.raise_for_status()
            break
        except Exception as e:
            if attempt == 2:
                print(f"Error: Failed to fetch {url} after 3 attempts: {e}")
                sys.exit(1)
            time.sleep(2 * (attempt + 1))
            
    soup = BeautifulSoup(res.text, "html.parser")
    table = soup.find("table")
    if not table:
        print(f"Error: No table found in HTML from {url}")
        sys.exit(1)
        
    rows = table.find_all("tr")
    if not rows:
        print("Error: Table has no rows")
        sys.exit(1)
        
    header_row = rows[0]
    headers_list = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]
    
    col_pos = -1
    col_change = -1
    col_track = -1
    col_days = -1
    col_peak = -1
    col_streams = -1
    
    for idx, h in enumerate(headers_list):
        h_lower = h.lower()
        if "pos" in h_lower or h_lower == "#":
            col_pos = idx
        elif "p+" in h_lower or "+/-" in h_lower or "change" in h_lower:
            col_change = idx
        elif "artist" in h_lower or "title" in h_lower or "track" in h_lower:
            col_track = idx
        elif "days" in h_lower or "wks" in h_lower or "weeks" in h_lower:
            col_days = idx
        elif "pk" in h_lower or "peak" in h_lower:
            col_peak = idx
        elif h_lower == "streams":
            col_streams = idx
            
    # Fallback to defaults if headers match fails
    if col_pos == -1: col_pos = 0
    if col_change == -1: col_change = 1
    if col_track == -1: col_track = 2
    if col_days == -1: col_days = 3
    if col_peak == -1: col_peak = 4
    if col_streams == -1: col_streams = 6
    
    week_date = extract_week_date(soup)
    tracks = []
    
    for r_idx in range(1, len(rows)):
        if len(tracks) >= 200:
            break
            
        cells = rows[r_idx].find_all("td")
        required_cols = max(col_pos, col_change, col_track, col_days, col_peak, col_streams) + 1
        if len(cells) < required_cols:
            continue
            
        try:
            rank = int(cells[col_pos].get_text(strip=True))
        except ValueError:
            continue
            
        change = cells[col_change].get_text(strip=True)
        if not change or change in ("0", "--", "—"):
            change = "0"
            
        track_cell = cells[col_track]
        a_tags = track_cell.find_all("a")
        artist = ""
        title = ""
        spotify_id = ""
        
        href = ""
        if len(a_tags) >= 2:
            artist = a_tags[0].get_text(strip=True)
            title = a_tags[1].get_text(strip=True)
            href = a_tags[1].get("href", "")
        elif len(a_tags) == 1:
            title = a_tags[0].get_text(strip=True)
            href = a_tags[0].get("href", "")
        else:
            track_text = track_cell.get_text(strip=True)
            artist, title = track_text.split(" - ", 1) if " - " in track_text else ("", track_text)

        if href:
            match = re.search(r"track/([a-zA-Z0-9]+)\.html", href)
            if match:
                spotify_id = match.group(1)
                

        streams = parse_num(cells[col_streams].get_text(strip=True))
        peak = parse_num(cells[col_peak].get_text(strip=True))
        weeks = parse_num(cells[col_days].get_text(strip=True))
        
        tracks.append({
            "rank": rank,
            "change": change,
            "title": title,
            "artist": artist,
            "spotifyId": spotify_id,
            "ytMusicId": "",
            "streams": streams,
            "peak": peak,
            "weeks": weeks
        })
        
    return {
        "country": country_code,
        "countryName": country_config["name"],
        "weekDate": week_date,
        "lastUpdated": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
        "tracks": tracks
    }

def load_ytmusic_cache(data_dir):
    cache_by_id = {}
    cache_by_name = {}
    
    data_path = Path(data_dir)
    if not data_path.exists():
        return cache_by_id, cache_by_name
        
    for p in data_path.glob("*.json"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                for t in data.get("tracks", []):
                    spotify_id = t.get("spotifyId")
                    yt_id = t.get("ytMusicId")
                    artist = t.get("artist")
                    title = t.get("title")
                    
                    if yt_id:
                        if spotify_id:
                            cache_by_id[spotify_id] = yt_id
                        if artist and title:
                            key = f"{artist.lower().strip()}|||{title.lower().strip()}"
                            cache_by_name[key] = yt_id
        except Exception as e:
            print(f"Warning: Failed to parse cache from {p}: {e}")
            
    return cache_by_id, cache_by_name

def get_auth_file(auth_path):
    if auth_path:
        if not Path(auth_path).exists():
            print(f"Error: Specified auth file not found: {auth_path}")
            sys.exit(1)
        return auth_path
        
    p = Path("browser.json")
    if p.exists():
        return str(p)
            
    print("Error: No authentication file found (browser.json).")
    print("Please run the authentication setup first.")
    sys.exit(1)

def main():
    args = parse_args()
    print(f"🚀 Starting YouTube Music sync for country: {args.country.upper()}")
    out_file = Path(args.data_dir) / f"{args.country}.json"
    
    # 1. Scrape chart data from Kworb
    chart = scrape_kworb(args.country)
    country_name = chart["countryName"]
    week_date = chart["weekDate"]
    tracks = chart["tracks"]
    
    print(f"Loaded {len(tracks)} tracks for {country_name} ({week_date}) from Kworb.")
    
    # Check if we already synchronized this week to save API quota
    if out_file.exists() and not args.force and not args.dry_run:
        try:
            with open(out_file, "r", encoding="utf-8") as f:
                cached_chart = json.load(f)
            cached_week_date = cached_chart.get("weekDate")
            print(f"Checking sync status: Cached Date = {cached_week_date}, Chart Date = {week_date}")
            if cached_week_date == week_date:
                print(f"ℹ️ Playlist for {country_name} is already up to date ({week_date}). Skipping sync.")
                return
        except Exception as e:
            print(f"⚠️ Warning: Failed to read cached chart file to compare weekDate: {e}")
            
    if args.force:
        print("Force flag active. Proceeding with sync regardless of cache date comparison.")
    
    # 2. Authenticate with YouTube Music
    auth_file = get_auth_file(args.auth)
    print(f"Authenticating using: {auth_file}")
    yt = YTMusic(auth_file)
        
    # 3. Load cache and enrich tracks with YouTube Music IDs
    cache_by_id, cache_by_name = load_ytmusic_cache(args.data_dir)
    print(f"Loaded cache from existing JSONs: {len(cache_by_id)} unique IDs, {len(cache_by_name)} name pairs.")
    
    resolved_count = 0
    cached_count = 0
    
    print("Enriching track metadata with YouTube Music IDs...")
    for idx, t in enumerate(tracks):
        if (idx + 1) % 50 == 0 or idx == 0 or idx == len(tracks) - 1:
            print(f"  Progress: {idx + 1}/{len(tracks)} tracks processed...")
            
        spotify_id = t.get("spotifyId")
        artist = t.get("artist")
        title = t.get("title")
        
        # Check Spotify ID cache
        yt_id = cache_by_id.get(spotify_id) if spotify_id else None
        
        # Check Name cache
        if not yt_id and artist and title:
            key = f"{artist.lower().strip()}|||{title.lower().strip()}"
            yt_id = cache_by_name.get(key)
            
        if yt_id:
            t["ytMusicId"] = yt_id
            cached_count += 1
        else:
            if artist and title:
                query = f"{artist} {title}"
                try:
                    # Delay to prevent rate limiting
                    time.sleep(random.uniform(0.3, 0.8))
                    
                    search_results = yt.search(query, filter="songs")
                    if search_results:
                        yt_id = search_results[0].get("videoId")
                        if yt_id:
                            print(f"    🔍 [Search] Resolved '{query}' to YouTube ID: {yt_id}")
                            t["ytMusicId"] = yt_id
                            # Add to in-memory cache
                            if spotify_id:
                                cache_by_id[spotify_id] = yt_id
                            key = f"{artist.lower().strip()}|||{title.lower().strip()}"
                            cache_by_name[key] = yt_id
                            
                            resolved_count += 1
                        else:
                            print(f"  ⚠ No videoId found for: {query}")
                    else:
                        print(f"  ⚠ No search results for: {query}")
                except Exception as e:
                    print(f"  ⚠ YTMusic search failed for '{query}': {e}")
                    
    print(f"YTMusic Enrichment: {resolved_count} resolved via search, {cached_count} resolved via cache.")
    
    # Deduplicate video IDs while preserving ranking order to prevent YTM API failure
    seen = set()
    new_video_ids = []
    for t in tracks:
        yt_id = t.get("ytMusicId")
        if yt_id and yt_id not in seen:
            seen.add(yt_id)
            new_video_ids.append(yt_id)
            
    print(f"Found {len(new_video_ids)} unique resolved YouTube Music track IDs out of {len(tracks)} tracks.")
    
    if not new_video_ids:
        print("No YouTube Music IDs found. Nothing to sync.")
        return

    if args.dry_run:
        print("\n--- DRY RUN ACTIVE ---")
        print(f"Would save updated data cache to {args.data_dir}/{args.country}.json")
        print(f"Would sync to playlist: Spotify Weekly {country_name} Top 200")
        print(f"Tracks to add (first 5): {new_video_ids[:5]}")
        print("Dry run complete. No mutations performed.")
        return

    # Save the updated chart data with resolved IDs to file
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(chart, f, indent=2, ensure_ascii=False)
    print(f"Saved updated data to {out_file}")

    # 4. Find or Create Playlist
    target_title = f"Spotify Weekly {country_name} Top 200"
    target_description = f"Synced automatically from Spotify weekly streaming chart on {week_date} via Spotify sync bot."
    
    print(f"Searching for existing playlist: '{target_title}'...")
    playlists = yt.get_library_playlists(limit=None)
    playlist_id = None
    for pl in playlists:
        if pl["title"] == target_title:
            playlist_id = pl["playlistId"]
            print(f"Found existing playlist: {target_title} (ID: {playlist_id})")
            break
            
    is_new_playlist = False
    if not playlist_id:
        print(f"Playlist not found. Creating new public playlist: '{target_title}'...")
        res = yt.create_playlist(
            title=target_title,
            description=target_description,
            privacy_status="PUBLIC"
        )
        if isinstance(res, str) and res != "STATUS_FAILED":
            playlist_id = res
        elif isinstance(res, dict) and "playlistId" in res:
            playlist_id = res["playlistId"]
        else:
            print(f"❌ Error: Failed to create playlist. Response: {res}")
            sys.exit(1)
        print(f"Created playlist ID: {playlist_id}")
        is_new_playlist = True

    # 5. Nuke and Rebuild
    if is_new_playlist:
        current_tracks = []
        current_count = 0
        print("Playlist is newly created and empty. Skipping track retrieval.")
    else:
        print("Fetching current playlist tracks...")
        playlist_details = yt.get_playlist(playlist_id, limit=None)
        current_tracks = playlist_details.get("tracks", [])
        current_count = len(current_tracks)
        print(f"Current playlist has {current_count} tracks.")
    
    # Remove all current tracks if any exist
    if current_count > 0:
        to_remove = [{"videoId": t["videoId"], "setVideoId": t["setVideoId"]} for t in current_tracks if t.get("setVideoId") and t.get("videoId")]
        if to_remove:
            print(f"Removing {len(to_remove)} tracks from YouTube Music playlist...")
            yt.remove_playlist_items(playlist_id, to_remove)
            print("Removal complete.")
        else:
            print("No tracks with valid setVideoId and videoId found. Skipping removal.")
        
    # Add new tracks in chunks of 50 to prevent timeouts/API limits
    print(f"Adding {len(new_video_ids)} tracks...")
    chunk_size = 50
    for i in range(0, len(new_video_ids), chunk_size):
        chunk = new_video_ids[i:i + chunk_size]
        print(f"Adding tracks {i+1} to {min(i + chunk_size, len(new_video_ids))}...")
        
        # Retry up to 3 times on transient failures
        for attempt in range(3):
            try:
                res = yt.add_playlist_items(playlist_id, chunk)
                status = res.get('status') if isinstance(res, dict) else res
                if status == 'STATUS_FAILED':
                    if attempt < 2:
                        print(f"  ⚠ Chunk upload failed with STATUS_FAILED, retrying (attempt {attempt + 2}/3)...")
                        time.sleep(2)
                        continue
                    else:
                        print(f"❌ Error: Failed to add chunk {i+1} to {min(i + chunk_size, len(new_video_ids))} to playlist. Response: {res}")
                        sys.exit(1)
                break  # Success
            except Exception as e:
                if attempt < 2:
                    print(f"  ⚠ Chunk upload exception: {e}, retrying (attempt {attempt + 2}/3)...")
                    time.sleep(2)
                else:
                    print(f"❌ Error: Failed to add chunk {i+1} to {min(i + chunk_size, len(new_video_ids))} due to exception: {e}")
                    sys.exit(1)
    print("Tracks added successfully.")
    
    # Update description to match the new Week Date
    print("Updating playlist description...")
    yt.edit_playlist(playlist_id, description=target_description)
    print("Description updated.")
    
    playlist_url = f"https://music.youtube.com/playlist?list={playlist_id}"
    print(f"\n🎉 Sync Complete! Playlist URL: {playlist_url}")

if __name__ == "__main__":
    main()
