import re
import time
import unicodedata
from rapidfuzz import fuzz

# Supported countries (Global and India only)
COUNTRIES = {
    "global": {"name": "Global", "slug": "global_weekly"},
    "in": {"name": "India", "slug": "in_weekly"}
}

BASE_URL = "https://kworb.net/spotify/country"

def retry_operation(func, attempts=3, delay=2, backoff_factor=1, linear_backoff=False, fatal=True, error_msg="Operation failed", retryable_exceptions=(Exception,)):
    current_delay = delay
    last_exception = None
    for attempt in range(attempts):
        try:
            return func()
        except Exception as e:
            last_exception = e
            if not isinstance(e, retryable_exceptions):
                raise
            if attempt < attempts - 1:
                wait_time = delay * (attempt + 1) if linear_backoff else current_delay
                print(f"  ⚠ {error_msg} (attempt {attempt + 1}/{attempts}) failed: {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
                if not linear_backoff:
                    current_delay *= backoff_factor
            else:
                print(f"❌ Error: {error_msg} failed after {attempts} attempts: {e}")
                if fatal:
                    raise last_exception
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
        # Preserves Indic script matras (India chart) while stripping Western diacritics
        elif cat.startswith('M'):
            if 0x0300 <= ord(c) <= 0x036F:
                continue
            cleaned.append(c)
    res = "".join(cleaned).lower()
    return " ".join(res.split())

# Precompiled regexes for title normalization
_KEYWORDS = (
    r"remaster|remastered|mix|edit|version|ver|explicit|clean|cover|"
    r"bonus track|audio|video|music\s+video|lyric|lyrics|"
    r"official|movie|ost|soundtrack|unplugged|acoustic|lofi|reprise|"
    r"single|album|radio|live"
)
_FROM_PATTERN = r"from\s+(?:[\"'\u201c\u201d\u2018\u2019].+?[\"'\u201c\u201d\u2018\u2019]|(?:the\s+)?(?:movie|soundtrack|ost|motion\s+picture)\b.*)"
_PATTERN_IN_BRACKETS = r"(?:" + _KEYWORDS + r")\b|" + _FROM_PATTERN

_RE_FEAT_BRACKETS = re.compile(r"\s*[([{-]\s*(?:feat\.?|featuring|ft\.?|with|w/|prod\.?)(?:\s|\b).*?[)\]}]")
_RE_FEAT_UNBRACKETED = re.compile(r"\b(?:feat\.?|featuring|ft\.?|prod\.?)(?:\s|\b).*")
_RE_WITH_SUFFIX = re.compile(r"\s*[-/]\s*(?:with|w/)(?:\s|\b).*")
_RE_BRACKETS_CLEAN = re.compile(r"\s*[([{]\s*(?:[^)\]}]*?\s+)?(?:" + _PATTERN_IN_BRACKETS + r")[^)\]}]*?[)\]}]")
_RE_SUFFIX_CLEAN = re.compile(r"\s*[-/]\s*(?:[^-/]*?\s+)?(?:" + _KEYWORDS + r")\b.*")

def clean_title(title):
    if not title:
        return ""
    
    # If title contains pipe '|', take the first part (common in video titles)
    if "|" in title:
        title = title.split("|")[0].strip()
        
    title = title.lower()
    # 1. Strip features in parentheses/brackets: (feat. ...), [w/ ...]
    title = _RE_FEAT_BRACKETS.sub("", title)
    title = _RE_FEAT_UNBRACKETED.sub("", title)
    title = _RE_WITH_SUFFIX.sub("", title)
    
    # 2. Strip remaster / version / edit in parentheses/brackets without crossing bracket boundaries
    title = _RE_BRACKETS_CLEAN.sub("", title)
    
    # 3. Strip hyphenated/slashed suffixes without crossing delimiter boundaries
    title = _RE_SUFFIX_CLEAN.sub("", title)
    
    return clean_string(title)

_VERSION_KEYWORDS = ["acoustic", "instrumental", "live", "cover", "tribute", "karaoke"]
_RE_REMIX = re.compile(r"\b(remix|rmx)\b")
_RE_VERSION_TAGS = {kw: re.compile(rf"\b{kw}\b") for kw in _VERSION_KEYWORDS}

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
    # Target and result must align on whether these tags are present using word boundaries.
    has_target_remix = bool(_RE_REMIX.search(target_lower))
    has_res_remix = bool(_RE_REMIX.search(res_lower))
    if has_target_remix != has_res_remix:
        return False
        
    for kw, pattern in _RE_VERSION_TAGS.items():
        if bool(pattern.search(target_lower)) != bool(pattern.search(res_lower)):
            return False
            
    clean_target = clean_title(target_title)
    clean_result = clean_title(res_title)
    ratio = fuzz.WRatio(clean_target, clean_result)
    return ratio >= threshold

_RE_ARTIST_TRIBUTE = re.compile(r"\b(tribute|cover|karaoke)\b")

def artist_matches(target_artist, result, threshold=85):
    """
    Checks if the target artist (or any of its collaboration components)
    is present in the result artists list. Used for ranking preference.
    """
    if not target_artist:
        return True
    res_artists = [a.get("name", "") for a in result.get("artists", [])]
    clean_target = clean_string(target_artist)
    target_lower = target_artist.lower()
    
    # Avoid matching tribute/cover/karaoke acts if the target artist doesn't explicitly contain them
    target_has_tribute = bool(_RE_ARTIST_TRIBUTE.search(target_lower))
    if not target_has_tribute:
        # Filter out result acts that are tribute/cover acts
        res_artists = [ra for ra in res_artists if not _RE_ARTIST_TRIBUTE.search(ra.lower())]
        if not res_artists:
            return False
                
    # Split duos/collabs to check components.
    # 1. Split on explicit collaboration conjunctions (&, ,, and)
    primary_parts = [p.strip() for p in re.split(r"[,&]|\band\b", target_artist) if p.strip()]
    
    components = []
    for part in primary_parts:
        components.append(clean_string(part))
        # Check for duo hyphenation (e.g. Sachet-Parampara, Vishal-Shekhar).
        # Only split if all parts are distinct names (len >= 3) to prevent
        # single-letter / prefix hyphenated names (Jay-Z, T-Pain) from false-matching.
        hyphen_parts = [hp.strip() for hp in re.split(r"[-–—]", part) if hp.strip()]
        if len(hyphen_parts) > 1 and all(len(hp) >= 3 for hp in hyphen_parts):
            for hp in hyphen_parts:
                cleaned_hp = clean_string(hp)
                if len(cleaned_hp) > 1:
                    components.append(cleaned_hp)
    
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



