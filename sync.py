#!/usr/bin/env python3
import json
import argparse
import sys
import re
import time
import random
import difflib
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

def retry_operation(func, attempts=3, delay=2, backoff_factor=1, linear_backoff=False, fatal=True, error_msg="Operation failed"):
    current_delay = delay
    for attempt in range(attempts):
        try:
            return func()
        except Exception as e:
            if attempt < attempts - 1:
                wait_time = delay * (attempt + 1) if linear_backoff else current_delay
                print(f"  ⚠ {error_msg} (attempt {attempt + 1}/{attempts}) failed: {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
                if not linear_backoff:
                    current_delay *= backoff_factor
            else:
                print(f"❌ Error: {error_msg} failed after {attempts} attempts: {e}")
                if fatal:
                    sys.exit(1)
                else:
                    return None

def clean_string(s):
    if not s:
        return ""
    # Lowercase, remove non-alphanumeric characters, and collapse spaces
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", "", s)
    return " ".join(s.split())

def verify_match(target_artist, target_title, result):
    """
    Checks if a search result resembles the target_artist and target_title.
    result is a dict returned by ytmusicapi (filter="songs").
    Expected keys: 'title', 'artists'.
    """
    res_title = result.get("title", "")
    res_artists = [a.get("name", "") for a in result.get("artists", [])]
    
    clean_target_art = clean_string(target_artist)
    clean_target_title = clean_string(target_title)
    clean_res_title = clean_string(res_title)
    
    # 1. Similarity check for title
    title_ratio = difflib.SequenceMatcher(None, clean_target_title, clean_res_title).ratio()
    
    # 2. Match artist
    artist_matched = False
    if not clean_target_art:
        artist_matched = True
    else:
        for ra in res_artists:
            clean_ra = clean_string(ra)
            # Check for direct substring match either way
            if clean_target_art in clean_ra or clean_ra in clean_target_art:
                artist_matched = True
                break
            # Or high similarity ratio
            if difflib.SequenceMatcher(None, clean_target_art, clean_ra).ratio() > 0.7:
                artist_matched = True
                break
                
    # Accept if title is highly similar and artist matches
    if title_ratio >= 0.75 and artist_matched:
        return True
    return False

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
    fallback_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"⚠️ Warning: Failed to parse week date from Kworb page. Falling back to today's date: {fallback_date}")
    return fallback_date

def parse_num(raw):
    raw_clean = re.sub(r"[^\d]", "", raw)
    return int(raw_clean) if raw_clean else 0

def fetch_kworb_html(country_code):
    country_config = COUNTRIES[country_code]
    url = f"{BASE_URL}/{country_config['slug']}.html"
    print(f"⏳ Scraping Kworb Weekly Chart: {url} ...")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MusicChartsDash/1.0)"}
    
    def fetch_url():
        res = requests.get(url, headers=headers, timeout=15)
        res.raise_for_status()
        return res.text

    html_content = retry_operation(
        fetch_url,
        attempts=3,
        delay=2,
        linear_backoff=True,
        fatal=True,
        error_msg=f"Failed to fetch {url}"
    )
    return html_content

def parse_kworb_html(html_content, country_code):
    country_config = COUNTRIES[country_code]
    soup = BeautifulSoup(html_content, "html.parser")
    table = soup.find("table")
    if not table:
        print(f"Error: No table found in HTML for {country_code}")
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
    col_weeks = -1
    col_peak = -1
    col_streams = -1
    
    for idx, h in enumerate(headers_list):
        h_lower = h.lower()
        if ("pos" in h_lower or h_lower == "#") and col_pos == -1:
            col_pos = idx
        elif ("p+" in h_lower or "+/-" in h_lower or "change" in h_lower) and col_change == -1:
            col_change = idx
        elif ("artist" in h_lower or "title" in h_lower or "track" in h_lower) and col_track == -1:
            col_track = idx
        elif ("days" in h_lower or "wks" in h_lower or "weeks" in h_lower) and col_weeks == -1:
            col_weeks = idx
        elif ("pk" in h_lower or "peak" in h_lower) and col_peak == -1:
            col_peak = idx
        elif h_lower == "streams" and col_streams == -1:
            col_streams = idx
            
    # Fallback to defaults if headers match fails
    fallbacks_used = []
    if col_pos == -1:
        col_pos = 0
        fallbacks_used.append("Pos (0)")
    if col_change == -1:
        col_change = 1
        fallbacks_used.append("Change (1)")
    if col_track == -1:
        col_track = 2
        fallbacks_used.append("Track (2)")
    if col_weeks == -1:
        col_weeks = 3
        fallbacks_used.append("Weeks (3)")
    if col_peak == -1:
        col_peak = 4
        fallbacks_used.append("Peak (4)")
    if col_streams == -1:
        col_streams = 6
        fallbacks_used.append("Streams (6)")
        
    if fallbacks_used:
        print(f"⚠️ Warning: Header detection failed for columns: {', '.join(fallbacks_used)}. Using fallback indices.")
    
    week_date = extract_week_date(soup)
    tracks = []
    
    for r_idx in range(1, len(rows)):
        if len(tracks) >= 200:
            break
            
        cells = rows[r_idx].find_all("td")
        required_cols = max(col_pos, col_change, col_track, col_weeks, col_peak, col_streams) + 1
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
        weeks = parse_num(cells[col_weeks].get_text(strip=True))
        
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
        
    if len(tracks) == 0:
        print("❌ Error: Scraped 0 tracks from Kworb page. This indicates a parser structure or column layout change.")
        sys.exit(1)
    elif len(tracks) < 100:
        print(f"⚠️ Warning: Scraped only {len(tracks)} tracks (expected ~200). Some rows might have failed to parse.")
        
    return {
        "country": country_code,
        "countryName": country_config["name"],
        "weekDate": week_date,
        "lastUpdated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "tracks": tracks
    }

def scrape_kworb(country_code):
    html_content = fetch_kworb_html(country_code)
    return parse_kworb_html(html_content, country_code)

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

def should_skip_sync(out_file, week_date, force, dry_run):
    if out_file.exists() and not force and not dry_run:
        try:
            with open(out_file, "r", encoding="utf-8") as f:
                cached_chart = json.load(f)
            cached_week_date = cached_chart.get("weekDate")
            print(f"Checking sync status: Cached Date = {cached_week_date}, Chart Date = {week_date}")
            if cached_week_date == week_date:
                return True
        except Exception as e:
            print(f"⚠️ Warning: Failed to read cached chart file to compare weekDate: {e}")
    return False

def find_or_create_playlist(yt, target_title, target_description):
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
        
        def create_pl():
            return yt.create_playlist(
                title=target_title,
                description=target_description,
                privacy_status="PUBLIC"
            )
            
        res = retry_operation(
            create_pl,
            attempts=3,
            delay=2,
            fatal=True,
            error_msg="Create playlist"
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
        
    if is_new_playlist:
        current_tracks = []
    else:
        print("Fetching current playlist tracks...")
        playlist_details = yt.get_playlist(playlist_id, limit=None)
        current_tracks = playlist_details.get("tracks", [])
        print(f"Current playlist has {len(current_tracks)} tracks.")
        
    return playlist_id, is_new_playlist, current_tracks

def resolve_track_ids(yt, tracks, cache_by_id, cache_by_name):
    resolved_count = 0
    cached_count = 0
    
    print("Enriching track metadata with YouTube Music IDs...")
    # WARNING: This loop MUST execute sequentially. Each successful resolution updates
    # cache_by_name, which is referenced by subsequent items. Parallelizing or reordering
    # this loop will break duplicate-detection, resulting in duplicate search queries.
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
                        matched_result = None
                        # Check top 5 results for verification
                        for r_idx, res in enumerate(search_results[:5]):
                            if verify_match(artist, title, res):
                                matched_result = res
                                break
                        
                        if matched_result:
                            yt_id = matched_result.get("videoId")
                            if yt_id:
                                print(f"    🔍 [Search] Resolved '{query}' to YouTube ID: {yt_id} (matched on result {r_idx + 1})")
                                t["ytMusicId"] = yt_id
                                # Add to in-memory cache
                                if spotify_id:
                                    cache_by_id[spotify_id] = yt_id
                                key = f"{artist.lower().strip()}|||{title.lower().strip()}"
                                cache_by_name[key] = yt_id
                                
                                resolved_count += 1
                            else:
                                print(f"  ⚠ No videoId found in verified match for: {query}")
                        else:
                            print(f"  ⚠️ Warning: Verification failed for '{query}'. None of the top {len(search_results[:5])} results passed the similarity criteria.")
                    else:
                        print(f"  ⚠ No search results for: {query}")
                except Exception as e:
                    print(f"  ⚠ YTMusic search failed for '{query}': {e}")
                    
    print(f"YTMusic Enrichment: {resolved_count} resolved via search, {cached_count} resolved via cache.")
    return tracks

def sync_playlist(yt, playlist_id, current_tracks, new_video_ids, target_description):
    # A. Add new tracks first (appends to the end of the playlist)
    print(f"Adding {len(new_video_ids)} new tracks...")
    chunk_size = 50
    for i in range(0, len(new_video_ids), chunk_size):
        chunk = new_video_ids[i:i + chunk_size]
        print(f"Adding tracks {i+1} to {min(i + chunk_size, len(new_video_ids))}...")
        
        def upload_chunk():
            res = yt.add_playlist_items(playlist_id, chunk)
            status = res.get('status') if isinstance(res, dict) else res
            if status == 'STATUS_FAILED':
                raise RuntimeError(f"STATUS_FAILED: {res}")
            return res

        retry_operation(
            upload_chunk,
            attempts=3,
            delay=2,
            fatal=True,
            error_msg=f"Add chunk {i+1} to {min(i + chunk_size, len(new_video_ids))} to playlist"
        )
    print("New tracks added successfully.")

    # B. Remove old tracks (removes original track instances by original setVideoId)
    current_count = len(current_tracks)
    if current_count > 0:
        to_remove = []
        skipped_remove_count = 0
        for t in current_tracks:
            vid = t.get("videoId")
            svid = t.get("setVideoId")
            if vid and svid:
                to_remove.append({"videoId": vid, "setVideoId": svid})
            else:
                skipped_remove_count += 1
        
        if skipped_remove_count > 0:
            print(f"⚠️ Warning: {skipped_remove_count} tracks in original playlist could not be marked for removal because they lack videoId or setVideoId.")
            
        if to_remove:
            print(f"Removing {len(to_remove)} old tracks from YouTube Music playlist...")
            retry_operation(
                lambda: yt.remove_playlist_items(playlist_id, to_remove),
                attempts=3,
                delay=2,
                fatal=True,
                error_msg="Remove tracks from playlist"
            )
            print("Removal of old tracks complete.")
        else:
            print("No tracks with valid setVideoId and videoId found. Skipping removal.")

    # C. Update description to match the new Week Date
    print("Updating playlist description...")
    retry_operation(
        lambda: yt.edit_playlist(playlist_id, description=target_description),
        attempts=3,
        delay=2,
        fatal=False,
        error_msg="Update playlist description"
    )
    print("Description update completed (or skipped on failure).")

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
    if should_skip_sync(out_file, week_date, args.force, args.dry_run):
        print(f"ℹ️ Playlist for {country_name} is already up to date ({week_date}). Skipping sync.")
        return
            
    if args.force:
        print("Force flag active. Proceeding with sync regardless of cache date comparison.")
    
    # 2. Authenticate with YouTube Music
    auth_file = get_auth_file(args.auth)
    print(f"Authenticating using: {auth_file}")
    yt = YTMusic(auth_file)
        
    # 3. Load cache and enrich tracks with YouTube Music IDs
    cache_by_id, cache_by_name = load_ytmusic_cache(args.data_dir)
    print(f"Loaded cache from existing JSONs: {len(cache_by_id)} unique IDs, {len(cache_by_name)} name pairs.")
    
    tracks = resolve_track_ids(yt, tracks, cache_by_id, cache_by_name)
    
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
        
    # 4. Find or Create Playlist
    target_title = f"Spotify Weekly {country_name} Top 200"
    target_description = f"Synced automatically from Spotify weekly streaming chart on {week_date} via Spotify sync bot."
    
    playlist_id, is_new_playlist, current_tracks = find_or_create_playlist(yt, target_title, target_description)
    
    # 5. Sync Playlist
    sync_playlist(yt, playlist_id, current_tracks, new_video_ids, target_description)
    
    # Save the updated chart data with resolved IDs to file (delayed to final step)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(chart, f, indent=2, ensure_ascii=False)
    print(f"Saved updated data to {out_file}")
    
    playlist_url = f"https://music.youtube.com/playlist?list={playlist_id}"
    print(f"\n🎉 Sync Complete! Playlist URL: {playlist_url}")

if __name__ == "__main__":
    main()
