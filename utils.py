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
    last_exception = None
    for attempt in range(attempts):
        try:
            return func()
        except Exception as e:
            last_exception = e
            if attempt < attempts - 1:
                wait_time = delay * (attempt + 1) if linear_backoff else current_delay
                print(f"  ⚠ {error_msg} (attempt {attempt + 1}/{attempts}) failed: {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
                if not linear_backoff:
                    current_delay *= backoff_factor
            else:
                print(f"❌ Error: {error_msg} failed after {attempts} attempts: {e}")
                if fatal:
                    if last_exception:
                        raise last_exception
                    else:
                        raise RuntimeError(f"{error_msg} failed after {attempts} attempts")
                else:
                    return None

def clean_string(s):
    if not s:
        return ""
    # Decompose accents to separate diacritics from base letters
    s = unicodedata.normalize('NFKD', s)
    cleaned = []
    for c in s:
        cat = unicodedata.category(c)
        # Keep letters (L), numbers (N), and spaces
        if cat.startswith(('L', 'N')) or c.isspace():
            cleaned.append(c)
        # Keep spacing/nonspacing marks (M) but discard standard diacritical marks (U+0300 - U+036F)
        elif cat.startswith('M'):
            if 0x0300 <= ord(c) <= 0x036F:
                continue
            cleaned.append(c)
    res = "".join(cleaned).lower()
    return " ".join(res.split())

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
    if not res_title:
        return False
        
    target_lower = target_title.lower()
    res_lower = res_title.lower()
    
    # Check for version mismatches (e.g. remix, acoustic, instrumental, live, cover, tribute, karaoke)
    # Target and result must align on whether these tags are present.
    # Note: 'rmx' is treated as synonymous with 'remix'
    has_target_remix = "remix" in target_lower or "rmx" in target_lower
    has_res_remix = "remix" in res_lower or "rmx" in res_lower
    if has_target_remix != has_res_remix:
        return False
        
    version_keywords = ["acoustic", "instrumental", "live", "cover", "tribute", "karaoke"]
    for kw in version_keywords:
        if (kw in target_lower) != (kw in res_lower):
            return False
            
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
    
    # Avoid matching tribute/cover/karaoke acts if the target artist doesn't explicitly contain them
    target_lower = target_artist.lower()
    for ra in res_artists:
        ra_lower = ra.lower()
        for kw in ["tribute", "cover", "karaoke"]:
            if kw in ra_lower and kw not in target_lower:
                return False
                
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


