import sys
import re
import time
import unicodedata
from pathlib import Path
from rapidfuzz import fuzz

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

def clean_title(title):
    if not title:
        return ""
    
    # If title contains pipe '|', take the first part (very common in video titles)
    if "|" in title:
        title = title.split("|")[0].strip()
        
    title = title.lower()
    # 1. Strip features in parentheses/brackets: (feat. ...), [feat. ...]
    title = re.sub(r"\s*[([{-]\s*(?:feat|featuring|ft|with|prod)\b.*?[)\]}]", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(?:feat|featuring|ft|prod)\b.*", "", title, flags=re.IGNORECASE)
    
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

def title_matches(target_title, result, threshold=85):
    """
    Checks if a search result's title is similar enough to the target title.
    The search query already contains the artist name, so YTM's search ranking
    handles artist relevance — we only need to verify the title matches.
    """
    res_title = result.get("title", "")
    clean_target = clean_title(target_title)
    clean_result = clean_title(res_title)
    ratio = fuzz.WRatio(clean_target, clean_result)
    return ratio >= threshold

def artist_matches(target_artist, result, threshold=85):
    """
    Checks if the target artist (or any of its collaboration components)
    is present in the result artists list. Used for ranking preference.
    """
    if not target_artist:
        return True
    res_artists = [a.get("name", "") for a in result.get("artists", [])]
    clean_target = clean_string(target_artist)
    
    # Split duos/collabs to check components
    components = [clean_string(c) for c in re.split(r"[-–—,&]|\band\b", target_artist)]
    components = [c for c in components if c]
    
    for ra in res_artists:
        clean_ra = clean_string(ra)
        if not clean_ra:
            continue
        if fuzz.token_set_ratio(clean_target, clean_ra) >= threshold:
            return True
        if any(comp and fuzz.token_set_ratio(comp, clean_ra) >= threshold for comp in components):
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
