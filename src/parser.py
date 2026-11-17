"""Turns a plain-English request into a VibeFinder user profile.

The offline parser uses keyword rules plus the knowledge base: if the
user names an activity but no genre ("something for the gym"), it
retrieves the genre notes whose 'Common uses' match the activity and
picks the best one. Every decision is recorded in `signals` so the
final answer can show its reasoning.
"""

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
LOW_ENERGY_CUES = ["low energy", "low-energy", "quiet", "soft", "slow", "sleep",
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

    def as_prefs(self) -> dict:
        """Shape expected by recommender.score_song."""
        return {"genre": self.genre or "", "mood": self.mood or "", "energy": self.energy}


def _contains(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", text) is not None


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
    lowered = text.lower()
    result = ParsedRequest()

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
        result.signals.append("low-energy cue found -> energy 0.30")
    elif any(_contains(lowered, c) for c in HIGH_ENERGY_CUES):
        result.energy = 0.9
        result.signals.append("high-energy cue found -> energy 0.90")
    elif result.mood:
        result.energy = MOOD_DEFAULT_ENERGY[result.mood]
        result.signals.append(f"energy {result.energy:.2f} defaulted from mood")
    else:
        result.signals.append("no energy cue -> neutral 0.50")

    return result
