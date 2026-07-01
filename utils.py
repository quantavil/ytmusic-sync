import sys
import re
import time
import difflib
import unicodedata
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
    # Normalize unicode to decompose accents (e.g. ń -> n, Ÿ -> Y)
    s = unicodedata.normalize('NFKD', s)
    s = s.encode('ascii', 'ignore').decode('ascii')
    
    # Lowercase, remove non-alphanumeric characters, and collapse spaces
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", "", s)
    return " ".join(s.split())

def extract_movie_name(title):
    if not title:
        return ""
    title_lower = title.lower()
    # Case 1: quoted movie name (e.g. from "Movie Name")
    m1 = re.search(r"\b(?:from\s+movie|from\s+ost|from\s+soundtrack|from|movie|ost|soundtrack)\s*[:\"]?\s*[\"“](.+?)[\"”]", title_lower)
    if m1:
        return clean_string(m1.group(1))
    # Case 2: unquoted movie name inside parentheses/brackets (e.g. (from Movie Name))
    m2 = re.search(r"\b(?:from\s+movie|from\s+ost|from\s+soundtrack|from|movie|ost|soundtrack)\s*[:]?\s*(.+?)(?=\s*[)\]}])", title_lower)
    if m2:
        return clean_string(m2.group(1))
    return ""

def clean_title(title):
    if not title:
        return ""
    
    # If title contains pipe '|', take the first part (very common in video titles)
    if "|" in title:
        title = title.split("|")[0].strip()
        
    title = title.lower()
    # 1. Strip features in parentheses/brackets: (feat. ...), [feat. ...]
    title = re.sub(r"\s*[([{-]\s*(?:feat|featuring|ft|with|prod)\b.*?[)\]}]", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(?:feat|featuring|ft|with|prod)\b.*", "", title, flags=re.IGNORECASE)
    
    # 2. Strip remaster / version / edit in parentheses/brackets
    keywords = (
        r"remaster|remastered|mix|edit|version|ver|explicit|clean|cover|"
        r"bonus track|from\s+.*|audio|video|music\s+video|lyric|lyrics|"
        r"official|movie|ost|soundtrack|unplugged|acoustic|lofi|reprise"
    )
    title = re.sub(r"\s*[([{]\s*(?:.*?\s+)?(?:" + keywords + r")\b.*?[)\]}]", "", title, flags=re.IGNORECASE)
    
    # 3. Strip hyphenated/slashed suffixes
    title = re.sub(r"\s*[-|/]\s*(?:.*?\s+)?(?:" + keywords + r"|single|album|radio|live)\b.*", "", title, flags=re.IGNORECASE)
    
    return clean_string(title)

def verify_match(target_artist, target_title, result, threshold=0.80):
    """
    Checks if a search result resembles the target_artist and target_title.
    result is a dict returned by ytmusicapi (filter="songs" or "videos").
    Expected keys: 'title', 'artists'.
    threshold controls the minimum title similarity ratio (default 0.80).
    """
    res_title = result.get("title", "")
    res_artists = [a.get("name", "") for a in result.get("artists", [])]
    res_album = result.get("album", {}).get("name", "") if result.get("album") else ""
    
    clean_target_art = clean_string(target_artist)
    clean_target_title = clean_title(target_title)
    clean_res_title = clean_title(res_title)
    
    # 1. Similarity check for title
    title_ratio = difflib.SequenceMatcher(None, clean_target_title, clean_res_title).ratio()
    
    # 2. Match artist
    artist_matched = False
    if not clean_target_art:
        artist_matched = True
    else:
        # Check if target artist has components (duos/collabs like Sachet-Parampara, Sachin-Jigar)
        artist_components = [clean_string(c) for c in re.split(r"[-–—,&]|\band\b", target_artist)]
        artist_components = [c for c in artist_components if c]
        
        for ra in res_artists:
            clean_ra = clean_string(ra)
            if not clean_ra:
                continue
            # Direct match
            if clean_target_art in clean_ra or clean_ra in clean_target_art:
                artist_matched = True
                break
            # Duo/collab component match
            if any(comp and (comp in clean_ra or clean_ra in comp) for comp in artist_components):
                artist_matched = True
                break
            # Similarity
            if difflib.SequenceMatcher(None, clean_target_art, clean_ra).ratio() > 0.7:
                artist_matched = True
                break
                
        # Fallback 1: Movie/Album name cross-verification
        # Useful for Bollywood where Spotify credits the composer and YTM credits the singer
        if not artist_matched:
            target_movie = extract_movie_name(target_title)
            if target_movie:
                clean_res_album = clean_string(res_album)
                clean_res_title_raw = clean_string(res_title)
                # Check if movie matches album or is in raw title
                if target_movie in clean_res_album or clean_res_album in target_movie or target_movie in clean_res_title_raw:
                    artist_matched = True
                    
        # Fallback 2: if artist doesn't match but is present in the video title (for video uploads)
        if not artist_matched and clean_target_art:
            clean_raw_res_title = clean_string(res_title)
            if clean_target_art in clean_raw_res_title:
                artist_matched = True
                # Strip the artist name from the result title and recalculate similarity ratio
                stripped_res_title = clean_string(clean_res_title.replace(clean_target_art, ""))
                title_ratio = difflib.SequenceMatcher(None, clean_target_title, stripped_res_title).ratio()
                
    # Accept if title is highly similar and artist matches
    if title_ratio >= threshold and artist_matched:
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
