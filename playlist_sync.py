import time
import random
import json
from pathlib import Path
from datetime import datetime, timezone

from utils import retry_operation, title_matches, artist_matches, clean_string
from youtube_client import call

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
    existing_title = None
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
                existing_title = title
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
        existing_title = target_title
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
        
    return playlist_id, current_tracks, existing_title, existing_description

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
            
    with open(log_path, "a", encoding="utf-8") as f:
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        for t in orphaned:
            f.write(f"{ts}\tplaylist={playlist_id}\ttrack={json.dumps(t)}\n")
    print(f"⚠️ Logged {len(orphaned)} orphaned/unremovable track entries to {log_path}")


def get_lis_elements(items, target_video_ids):
    # Map each videoId to its target index
    target_index_map = {vid: idx for idx, vid in enumerate(target_video_ids)}
    
    # We want to find the LIS of items based on their target indices
    valid_items = [item for item in items if item.get("videoId") in target_index_map]
    if not valid_items:
        return set()
        
    n = len(valid_items)
    dp = [1] * n
    parent = [-1] * n
    
    for i in range(1, n):
        idx_i = target_index_map[valid_items[i]["videoId"]]
        for j in range(i):
            idx_j = target_index_map[valid_items[j]["videoId"]]
            if idx_j < idx_i and dp[j] + 1 > dp[i]:
                dp[i] = dp[j] + 1
                parent[i] = j
                
    max_len = max(dp)
    curr_idx = dp.index(max_len)
    
    lis_set_ids = set()
    while curr_idx != -1:
        lis_set_ids.add(valid_items[curr_idx]["setVideoId"])
        curr_idx = parent[curr_idx]
        
    return lis_set_ids


def sync_playlist(youtube, playlist_id, current_tracks, new_video_ids, target_title, target_description, existing_title=None, existing_description=None, data_dir="data"):
    # 1. Identify truly orphaned tracks (lacking setVideoId)
    orphaned = [t for t in current_tracks if not t.get("setVideoId")]
    if orphaned:
        print(f"⚠️ Warning: {len(orphaned)} tracks lack setVideoId and cannot be managed.")
        _log_orphaned_tracks(data_dir, playlist_id, orphaned)
        
    # Filter out orphaned tracks for our state tracking since we can't move/delete them anyway
    current_state = [t for t in current_tracks if t.get("setVideoId")]
    
    # Identify remaining current tracks that we want to keep
    seen_vids = set()
    remaining_current = []
    for item in current_state:
        vid = item.get("videoId")
        if vid and vid in new_video_ids and vid not in seen_vids:
            seen_vids.add(vid)
            remaining_current.append(item)
            
    # A. Reorder the remaining current tracks first to match their relative target order.
    # We use the Longest Increasing Subsequence (LIS) to minimize the number of move operations.
    target_index_map = {vid: idx for idx, vid in enumerate(new_video_ids)}
    lis_set_ids = get_lis_elements(remaining_current, new_video_ids)
    target_remaining = sorted(remaining_current, key=lambda x: target_index_map[x["videoId"]])
    
    print("Reordering existing tracks to match target relative order...")
    for target_rel_idx, item in enumerate(target_remaining):
        vid = item["videoId"]
        item_id = item["setVideoId"]
        curr_idx = current_state.index(item)
        
        if item_id not in lis_set_ids:
            if curr_idx != target_rel_idx:
                print(f"Repositioning track {vid} (current pos: {curr_idx}, target pos: {target_rel_idx})...")
                
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
                                "position": target_rel_idx
                            }
                        }
                    ).execute()
                    
                call(update_item, error_msg=f"Move item {item_id} to position {target_rel_idx}")
                current_state.remove(item)
                current_state.insert(target_rel_idx, item)
                time.sleep(0.2)
                
    # B. Insert new tracks at their correct indices (Add)
    print(f"Synchronizing playlist content and order (Target tracks: {len(new_video_ids)})...")
    for target_idx, vid in enumerate(new_video_ids):
        # Find where this video is in our current_state in memory
        curr_idx = -1
        for idx, item in enumerate(current_state):
            # Only match items that are part of the target list (ignore to_delete items at the end)
            if item["videoId"] == vid and idx < len(new_video_ids):
                curr_idx = idx
                break
                
        if curr_idx == -1:
            # Video is not in the playlist yet -> Insert at the target index
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
            # Already in the correct position or relatively ordered
            pass
            
    # C. Execute deletions last (Remove)
    to_delete = current_state[len(new_video_ids):]
    if to_delete:
        print(f"Removing {len(to_delete)} old/duplicate tracks from YouTube Music playlist...")
        for idx, item in enumerate(to_delete):
            item_id = item["setVideoId"]
            print(f"Removing track {idx+1}/{len(to_delete)} (ID: {item_id})...")
            def delete_item():
                return youtube.playlistItems().delete(id=item_id).execute()
            call(delete_item, error_msg=f"Delete playlist item {item_id}")
            time.sleep(0.2)
        print("Removal of old tracks complete.")
    else:
        print("No tracks need to be removed.")
        
    print("Playlist content and order synchronization complete.")
    
    # D. Update title and/or description if casing or content differs
    if existing_title == target_title and existing_description == target_description:
        print("Playlist title and description are already up to date. Skipping update to save quota.")
        return
        
    print("Updating playlist title and description...")
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
        
    call(edit_pl, error_msg="Update playlist details")
    print("Playlist details update completed.")