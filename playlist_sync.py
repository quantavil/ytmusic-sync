import time
import random
import json
from pathlib import Path

from utils import retry_operation, title_matches, artist_matches, clean_string
from youtube_client import call

RANK_SHIFT_THRESHOLD = 5

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
                            key = f"{clean_string(artist)}|||{clean_string(title)}"
                            cache_by_name[key] = yt_id
        except Exception as e:
            print(f"Warning: Failed to parse cache from {p}: {e}")
            
    return cache_by_id, cache_by_name

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

def find_or_create_playlist(youtube, target_title, target_description):
    print(f"Searching for existing playlist: '{target_title}'...")
    playlist_id = None
    existing_description = None
    next_page_token = None
    
    while True:
        def list_playlists():
            return youtube.playlists().list(
                mine=True,
                part="snippet,id",
                maxResults=50,
                pageToken=next_page_token
            ).execute()
            
        res = call(list_playlists, error_msg="List mine playlists")
        items = res.get("items", [])
        
        for pl in items:
            title = pl["snippet"]["title"]
            if title.strip().lower() == target_title.strip().lower():
                playlist_id = pl["id"]
                existing_description = pl["snippet"].get("description", "")
                print(f"Found existing playlist: {title} (ID: {playlist_id})")
                break
                
        if playlist_id:
            break
            
        next_page_token = res.get("nextPageToken")
        if not next_page_token:
            break
            
    is_new_playlist = False
    if not playlist_id:
        print(f"Playlist not found. Creating new public playlist: '{target_title}'...")
        
        def create_pl():
            return youtube.playlists().insert(
                part="snippet,status",
                body={
                    "snippet": {
                        "title": target_title,
                        "description": target_description
                    },
                    "status": {
                        "privacyStatus": "public"
                    }
                }
            ).execute()
            
        res = call(create_pl, error_msg="Create playlist")
        playlist_id = res["id"]
        print(f"Created playlist ID: {playlist_id}")
        is_new_playlist = True
        existing_description = target_description
        
    if is_new_playlist:
        current_tracks = []
    else:
        print("Fetching current playlist tracks...")
        current_tracks = []
        next_page_token = None
        
        while True:
            def list_items():
                return youtube.playlistItems().list(
                    playlistId=playlist_id,
                    part="snippet,id",
                    maxResults=50,
                    pageToken=next_page_token
                ).execute()
                
            res = call(list_items, error_msg="List playlist items")
            for item in res.get("items", []):
                snippet = item.get("snippet", {})
                video_id = snippet.get("resourceId", {}).get("videoId")
                playlist_item_id = item.get("id")
                current_tracks.append({
                    "videoId": video_id,
                    "setVideoId": playlist_item_id
                })
            next_page_token = res.get("nextPageToken")
            if not next_page_token:
                break
                
        print(f"Current playlist has {len(current_tracks)} tracks.")
        
    return playlist_id, current_tracks, existing_description

def _search_and_match(yt, query, title, artist, filter_type):
    """
    Runs a single YTM search (with retry on transient failure) and returns
    (matched_result_or_None, matched_index_or_-1, is_artist_matched).
    Retries are non-fatal: a track that still fails after retries returns
    (None, -1, False) rather than crashing the whole run.
    """
    def do_search():
        time.sleep(random.uniform(0.3, 0.8))  # rate-limit courtesy delay
        return yt.search(query, filter=filter_type)

    results = retry_operation(
        do_search,
        attempts=3,
        delay=2,
        fatal=False,
        error_msg=f"YTMusic '{filter_type}' search for '{query}'"
    )
    if not results:
        return None, -1, False

    candidate_result, candidate_idx = None, -1
    for r_idx, res in enumerate(results[:3]):
        if title_matches(title, res):
            if artist_matches(artist, res):
                return res, r_idx, True
            elif candidate_result is None:
                candidate_result, candidate_idx = res, r_idx

    return candidate_result, candidate_idx, False


def resolve_track_ids(yt, tracks, cache_by_id, cache_by_name):
    resolved_count = 0
    cached_count = 0
    failed_count = 0

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
            key = f"{clean_string(artist)}|||{clean_string(title)}"
            yt_id = cache_by_name.get(key)

        if yt_id:
            t["ytMusicId"] = yt_id
            if spotify_id and spotify_id not in cache_by_id:
                cache_by_id[spotify_id] = yt_id
            cached_count += 1
            continue

        if not (artist and title):
            print(f"  ⚠️ Warning: Skipping track due to missing metadata — Artist: '{artist}', Title: '{title}'")
            failed_count += 1
            continue

        query = f"{artist} {title}"
        search_type = "songs"
        matched_result, matched_idx, is_artist_matched = _search_and_match(yt, query, title, artist, "songs")

        # Fall back to videos if songs search found nothing OR the songs match
        # had no usable videoId (edge case: matched metadata but no playable id).
        if not matched_result or not matched_result.get("videoId"):
            if not matched_result:
                print(f"    ⏭️ Songs search miss for '{query}', trying videos...")
            else:
                print(f"  ⚠ Songs match for '{query}' had no videoId, trying videos...")
            matched_result, matched_idx, is_artist_matched = _search_and_match(yt, query, title, artist, "videos")
            search_type = "videos"

        if matched_result and matched_result.get("videoId"):
            yt_id = matched_result["videoId"]
            res_title = matched_result.get("title", "")
            res_artists = ", ".join([a.get("name", "") for a in matched_result.get("artists", []) if a.get("name")])
            match_name = f"{res_artists} - {res_title}" if res_artists else res_title
            
            if is_artist_matched:
                print(f"    🔍 [{search_type.capitalize()}] Resolved '{query}' ➔ '{match_name}' ({yt_id}) (result {matched_idx + 1})")
            else:
                print(f"    ⚠️ Warning: Fallback Title-Only Match (Artist Mismatch) for '{query}' ➔ '{match_name}' ({yt_id}) (result {matched_idx + 1})")
                
            t["ytMusicId"] = yt_id
            if spotify_id:
                cache_by_id[spotify_id] = yt_id
            key = f"{clean_string(artist)}|||{clean_string(title)}"
            cache_by_name[key] = yt_id
            resolved_count += 1
        else:
            print(f"  ⚠️ Unresolved: '{query}' — no title match / no videoId in top 3 songs or videos (after retries).")
            failed_count += 1

    print(f"YTMusic Enrichment: {resolved_count} resolved via search, {cached_count} resolved via cache, {failed_count} failed.")
    return tracks, resolved_count, cached_count, failed_count

def _log_orphaned_tracks(data_dir, playlist_id, orphaned):
    """Append unremovable playlist entries to a durable log so they don't just
    scroll off in CI output. These are entries YTM returned without a
    setVideoId (unmanageable videos)."""
    if not orphaned:
        return
    log_path = Path(data_dir) / "orphaned_tracks.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Check size to prevent unbounded growth (rotate at 1MB)
    if log_path.exists() and log_path.stat().st_size > 1024 * 1024:
        try:
            backup_path = log_path.with_suffix(".log.old")
            log_path.replace(backup_path)
        except Exception as e:
            print(f"Warning: Failed to rotate orphaned_tracks.log: {e}")
            
    from datetime import datetime, timezone
    with open(log_path, "a", encoding="utf-8") as f:
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        for t in orphaned:
            f.write(f"{ts}\tplaylist={playlist_id}\ttrack={json.dumps(t)}\n")
    print(f"⚠️ Logged {len(orphaned)} orphaned/unremovable track entries to {log_path}")


def sync_playlist(youtube, playlist_id, current_tracks, new_video_ids, target_title, target_description, existing_description=None, data_dir="data"):
    # 1. Identify truly orphaned tracks (lacking setVideoId)
    orphaned = [t for t in current_tracks if not t.get("setVideoId")]
    if orphaned:
        print(f"⚠️ Warning: {len(orphaned)} tracks lack setVideoId and cannot be managed.")
        _log_orphaned_tracks(data_dir, playlist_id, orphaned)
        
    # 2. Identify deletions and duplicates
    seen_vids = set()
    to_delete = []
    remaining_current = []
    
    for item in current_tracks:
        vid = item.get("videoId")
        item_id = item.get("setVideoId")
        if not item_id:
            continue
        if not vid or vid not in new_video_ids or vid in seen_vids:
            to_delete.append(item_id)
        else:
            seen_vids.add(vid)
            remaining_current.append(item)
            
    # A. Execute deletions
    if to_delete:
        print(f"Removing {len(to_delete)} old/duplicate tracks from YouTube Music playlist...")
        for idx, item_id in enumerate(to_delete):
            print(f"Removing track {idx+1}/{len(to_delete)} (ID: {item_id})...")
            def delete_item():
                return youtube.playlistItems().delete(id=item_id).execute()
            call(delete_item, error_msg=f"Delete playlist item {item_id}")
            time.sleep(0.2)
        print("Removal of old tracks complete.")
    else:
        print("No tracks need to be removed.")
        
    # B. Insert new tracks and reorder shifted tracks
    # We maintain current_state in memory to track current playlist positions.
    current_state = list(remaining_current)
    
    print(f"Synchronizing playlist content and order (Target tracks: {len(new_video_ids)})...")
    for target_idx, vid in enumerate(new_video_ids):
        # Find where this video is in our current_state in memory
        curr_idx = -1
        for idx, item in enumerate(current_state):
            if item["videoId"] == vid:
                curr_idx = idx
                break
                
        if curr_idx == -1:
            # Case 1: Video is not in the playlist -> Insert at the target index
            print(f"Inserting new track {vid} at position {target_idx}...")
            
            def insert_item():
                return youtube.playlistItems().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "playlistId": playlist_id,
                            "resourceId": {
                                "kind": "youtube#video",
                                "videoId": vid
                            },
                            "position": target_idx
                        }
                    }
                ).execute()
                
            res = call(insert_item, error_msg=f"Insert video {vid} at position {target_idx}")
            new_item_id = res["id"]
            current_state.insert(target_idx, {"videoId": vid, "setVideoId": new_item_id})
            time.sleep(0.2)
            
        else:
            # Case 2: Video is in the playlist -> Check if we need to update its position
            shift = abs(curr_idx - target_idx)
            if shift > RANK_SHIFT_THRESHOLD:
                print(f"Repositioning track {vid} (current pos: {curr_idx}, target pos: {target_idx}, shift: {shift} > threshold {RANK_SHIFT_THRESHOLD})...")
                item_id = current_state[curr_idx]["setVideoId"]
                
                def update_item():
                    return youtube.playlistItems().update(
                        part="snippet",
                        body={
                            "id": item_id,
                            "snippet": {
                                "playlistId": playlist_id,
                                "resourceId": {
                                    "kind": "youtube#video",
                                    "videoId": vid
                                },
                                "position": target_idx
                            }
                        }
                    ).execute()
                    
                call(update_item, error_msg=f"Move item {item_id} to position {target_idx}")
                # Update in-memory state: move the item
                item = current_state.pop(curr_idx)
                current_state.insert(target_idx, item)
                time.sleep(0.2)
            else:
                # Do nothing, leave it at curr_idx (it's close enough!)
                pass
                
    print("Playlist content and order synchronization complete.")
    
    # C. Update description to match the new Week Date
    if existing_description == target_description:
        print("Playlist description is already up to date. Skipping description update to save quota.")
        return
        
    print("Updating playlist description...")
    def edit_pl():
        return youtube.playlists().update(
            part="snippet",
            body={
                "id": playlist_id,
                "snippet": {
                    "title": target_title,
                    "description": target_description
                }
            }
        ).execute()
        
    call(edit_pl, attempts=3, delay=2, error_msg="Update playlist description")
    print("Description update completed.")