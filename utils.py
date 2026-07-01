import sys
import re
import time
import difflib
from pathlib import Path

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
            # Check for direct substring match either way (ignoring empty strings)
            if clean_ra and (clean_target_art in clean_ra or clean_ra in clean_target_art):
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

def parse_num(raw):
    raw_clean = re.sub(r"[^\d]", "", raw)
    return int(raw_clean) if raw_clean else 0

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
