"""Turns a plain-English request into a VibeFinder user profile.

The offline parser uses keyword rules plus the knowledge base: if the
user names an activity but no genre ("something for the gym"), it
retrieves the genre notes whose 'Common uses' match the activity and
picks the best one. Every decision is recorded in `signals` so the
final answer can show its reasoning.
"""

import difflib
import re
from dataclasses import dataclass, field
from typing import List, Optional

from src.knowledge_base import KnowledgeBase

# Words a user might type -> canonical genre in songs.csv.
# Longer phrases are checked first so "indie pop" wins over "pop".
GENRE_SYNONYMS = {
    "indie pop": ["indie pop", "indie"],
    "lofi": ["lofi", "lo-fi", "lo fi", "chillhop"],
    "hip-hop": ["hip-hop", "hip hop", "hiphop", "rap"],
    "r&b": ["r&b", "rnb", "r and b"],
    "edm": ["edm", "electronic", "techno", "house music", "dance music"],
    "synthwave": ["synthwave", "retrowave", "80s synth"],
    "ambient": ["ambient"],
    "jazz": ["jazz"],
    "soul": ["soul"],
    "reggae": ["reggae"],
    "folk": ["folk", "acoustic"],
    "rock": ["rock", "metal", "punk"],
    "pop": ["pop"],
}

MOOD_SYNONYMS = {
    "happy": ["happy", "upbeat", "cheerful", "joyful", "celebrate", "party", "sunny", "good mood"],
    "chill": ["chill", "calm", "mellow", "laid back", "laid-back", "lowkey", "low-key"],
    "intense": ["intense", "hype", "pumped", "aggressive", "workout", "gym", "run", "running", "lift"],
    "relaxed": ["relaxed", "relax", "relaxing", "cozy", "gentle", "unwind", "coffee"],
    "moody": ["moody", "sad", "dark", "melancholy", "night drive", "introspective", "rainy"],
    "focused": ["focus", "focused", "study", "studying", "concentrate", "coding", "homework", "deep work"],
}

# Default energy when the user gives no explicit energy cue.
MOOD_DEFAULT_ENERGY = {
    "happy": 0.8, "chill": 0.4, "intense": 0.9,
    "relaxed": 0.35, "moody": 0.55, "focused": 0.4,
}

HIGH_ENERGY_CUES = ["high energy", "high-energy", "energetic", "loud", "fast", "hype", "banger", "pump"]
LOW_ENERGY_CUES = ["low energy", "low-energy", "quiet", "soft", "slow", "sleep", "asleep", "bedtime",
                   "nothing too loud", "not too loud", "background", "gentle"]

NEGATION = r"(?:no|not|without|except|nothing|avoid|skip|hate)"


@dataclass
class ParsedRequest:
    genre: Optional[str] = None
    mood: Optional[str] = None
    energy: float = 0.5
    excluded_genres: List[str] = field(default_factory=list)
    genre_source: str = "none"      # "stated" | "inferred" | "none"
    mood_source: str = "none"       # "stated" | "none"
    signals: List[str] = field(default_factory=list)
    source: str = "rules"           # "rules" | "claude"
    # Stretch: "low" / "high" when the user gave a strong energy cue
    # (sleep, bedtime, hype...). The agent then treats energy as a hard
    # limit instead of just one of three score terms.
    energy_mode: Optional[str] = None
    corrections: List[str] = field(default_factory=list)

    def as_prefs(self) -> dict:
        """Shape expected by recommender.score_song."""
        return {"genre": self.genre or "", "mood": self.mood or "", "energy": self.energy}


def _contains(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", text) is not None


# Single words the fuzzy matcher may correct typos towards.
_FUZZY_VOCAB = sorted({w for words in list(GENRE_SYNONYMS.values()) + list(MOOD_SYNONYMS.values())
                       for w in words if " " not in w and len(w) >= 4})
FUZZY_CUTOFF = 0.8


def correct_typos(text: str, protected=frozenset()):
    """Stretch: fix small typos ("lofy", "jaz z", "chil") before parsing.

    Only words of 4+ letters that are close (difflib ratio >= 0.8) to a known
    genre/mood keyword are changed, so ordinary words are left alone.
    Words in `protected` (every word the knowledge base uses, e.g. "reading")
    are never changed, so a real activity is not "corrected" into a mood.
    Returns (corrected_text, ["chil -> chill", ...]).
    """
    known = set(_FUZZY_VOCAB) | set(protected)
    fixes = []

    def fix(match):
        word = match.group(0)
        if len(word) < 4 or word in known:
            return word
        close = difflib.get_close_matches(word, _FUZZY_VOCAB, n=1, cutoff=FUZZY_CUTOFF)
        if close:
            fixes.append(f"{word} -> {close[0]}")
            return close[0]
        return word

    corrected = re.sub(r"[a-z][a-z\-]*", fix, text)
    return corrected, fixes


def _find_excluded_genres(text: str) -> List[str]:
    excluded = []
    for genre, words in GENRE_SYNONYMS.items():
        for word in words:
            if re.search(rf"\b{NEGATION}\b[\w\s]{{0,12}}?(?<![a-z]){re.escape(word)}(?![a-z])", text):
                excluded.append(genre)
                break
    return excluded


def parse_request(text: str, kb: KnowledgeBase) -> ParsedRequest:
    """Rule-based + retrieval-assisted parse of a natural-language request."""
    result = ParsedRequest()
    lowered, fixes = correct_typos(text.lower(), kb.vocabulary())
    if fixes:
        result.corrections = fixes
        result.signals.append("typo correction: " + ", ".join(fixes))

    # 1. Genres the user said they do NOT want.
    result.excluded_genres = _find_excluded_genres(lowered)
    if result.excluded_genres:
        result.signals.append(f"excluded genres: {', '.join(result.excluded_genres)}")

    # 2. Stated genre (longest phrase first, skipping excluded ones).
    for genre, words in GENRE_SYNONYMS.items():
        if genre in result.excluded_genres:
            continue
        if any(_contains(lowered, w) for w in words):
            result.genre, result.genre_source = genre, "stated"
            result.signals.append(f"genre '{genre}' stated in request")
            break

    # 3. Stated mood.
    for mood, words in MOOD_SYNONYMS.items():
        if any(_contains(lowered, w) for w in words):
            result.mood, result.mood_source = mood, "stated"
            result.signals.append(f"mood '{mood}' matched a keyword")
            break

    # 4. No genre? Retrieve one from the knowledge base by activity (RAG step).
    if result.genre is None:
        hits = kb.search(lowered, kind="genre", top_n=1, exclude=result.excluded_genres)
        if hits:
            doc, score = hits[0]
            result.genre, result.genre_source = doc.name, "inferred"
            result.signals.append(
                f"genre '{doc.name}' inferred from knowledge base (uses: {doc.uses})"
            )

    # 5. Energy: explicit number > cue words > mood default > 0.5.
    number = re.search(r"energy\D{0,5}(0?\.\d+|1(?:\.0+)?|\d{1,3}\s*%)", lowered)
    if number:
        raw = number.group(1).replace("%", "").strip()
        value = float(raw)
        result.energy = value / 100 if value > 1 else value
        result.signals.append(f"energy {result.energy:.2f} given explicitly")
    elif any(_contains(lowered, c) for c in LOW_ENERGY_CUES):
        result.energy = 0.3
        result.energy_mode = "low"
        result.signals.append("low-energy cue found -> energy 0.30 (treated as a limit)")
    elif any(_contains(lowered, c) for c in HIGH_ENERGY_CUES):
        result.energy = 0.9
        result.energy_mode = "high"
        result.signals.append("high-energy cue found -> energy 0.90 (treated as a limit)")
    elif result.mood:
        result.energy = MOOD_DEFAULT_ENERGY[result.mood]
        result.signals.append(f"energy {result.energy:.2f} defaulted from mood")
    else:
        result.signals.append("no energy cue -> neutral 0.50")

    return result
