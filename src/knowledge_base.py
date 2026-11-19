"""Knowledge base for VibeFinder 2.0.

Loads short notes about genres and moods from data/knowledge/*.md and
retrieves the notes that are most relevant to a user's request. The
retrieved notes are used twice:

1. By the parser, to infer a genre from an activity ("music for the gym")
   when the user never names a genre.
2. By the explainer, so each recommendation reason is grounded in what the
   knowledge base actually says about that genre and mood.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "data" / "knowledge"

STOPWORDS = {
    "a", "an", "and", "the", "for", "to", "of", "in", "on", "me", "my", "i",
    "some", "something", "music", "songs", "song", "play", "want", "need",
    "give", "with", "that", "is", "it", "while", "like", "please", "can",
    "you", "be", "too", "nothing", "just", "good", "best", "typical",
    "common", "uses", "related", "energy", "sound", "but", "or", "at",
}


@dataclass
class KnowledgeDoc:
    """One retrievable note, e.g. kind='genre', name='lofi'."""
    kind: str
    name: str
    text: str

    @property
    def uses(self) -> str:
        """The 'Common uses' / 'Good for' sentence, if present."""
        match = re.search(r"(Common uses|Good for):\s*([^.]*)", self.text)
        return match.group(2).strip() if match else ""


def tokenize(text: str) -> List[str]:
    """Lowercase word tokens with stopwords removed."""
    words = re.findall(r"[a-z&\-]+", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def _stem(word: str) -> str:
    """Very small stemmer so 'workouts' matches 'workout', 'studying' matches 'study'."""
    for suffix in ("ying", "ing", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            base = word[: -len(suffix)]
            return base + "y" if suffix == "ying" else base
    return word


# Everyday words -> the vocabulary the knowledge notes use.
# Added after evaluation case 5 ("fall asleep") failed to retrieve 'ambient'.
QUERY_EXPANSIONS = {
    "asleep": "sleep", "bedtime": "sleep", "nap": "sleep",
    "gym": "workout", "lifting": "workout", "exercise": "workout",
    "drive": "drives", "driving": "drives", "read": "reading",
    "chilling": "chill", "beach": "beach", "dinner": "dinner",
}


def expand_query(query: str) -> str:
    """Append canonical words for any everyday synonyms in the query."""
    extra = [QUERY_EXPANSIONS[w] for w in tokenize(query) if w in QUERY_EXPANSIONS]
    return query + (" " + " ".join(extra) if extra else "")


class KnowledgeBase:
    """In-memory store of genre and mood notes with keyword retrieval."""

    def __init__(self, docs: List[KnowledgeDoc]):
        self.docs = docs
        self._by_key: Dict[tuple, KnowledgeDoc] = {(d.kind, d.name): d for d in docs}

    @classmethod
    def load(cls, directory: Path = KNOWLEDGE_DIR) -> "KnowledgeBase":
        """Parse every '## name' section in genres.md and moods.md."""
        docs: List[KnowledgeDoc] = []
        for filename, kind in (("genres.md", "genre"), ("moods.md", "mood")):
            path = Path(directory) / filename
            if not path.exists():
                raise FileNotFoundError(f"Knowledge file missing: {path}")
            sections = re.split(r"^## ", path.read_text(encoding="utf-8"), flags=re.M)
            for section in sections:
                section = section.strip()
                if not section:
                    continue
                name, _, body = section.partition("\n")
                docs.append(KnowledgeDoc(kind, name.strip().lower(), body.strip()))
        return cls(docs)

    def get(self, kind: str, name: Optional[str]) -> Optional[KnowledgeDoc]:
        if not name:
            return None
        return self._by_key.get((kind, name.lower()))

    def vocabulary(self) -> set:
        """Every word that appears in the notes (protected from typo fixes)."""
        if not hasattr(self, "_vocab"):
            self._vocab = {w for d in self.docs for w in re.findall(r"[a-z]+", d.text.lower())}
            self._vocab |= {_stem(w) for w in self._vocab} | STOPWORDS | set(QUERY_EXPANSIONS)
        return self._vocab

    def names(self, kind: str) -> List[str]:
        return [d.name for d in self.docs if d.kind == kind]

    def search(self, query: str, kind: Optional[str] = None,
               top_n: int = 3, exclude: Iterable[str] = ()) -> List[tuple]:
        """Rank docs by keyword overlap with their 'uses' sentence.

        Returns a list of (doc, score) with score > 0, best first. Only the
        uses sentence is matched, so a word like 'study' points to genres
        people actually study to rather than any genre that mentions it.
        """
        query_stems = {_stem(w) for w in tokenize(expand_query(query))}
        excluded = {e.lower() for e in exclude}
        results = []
        for doc in self.docs:
            if kind and doc.kind != kind:
                continue
            if doc.name in excluded:
                continue
            doc_stems = {_stem(w) for w in tokenize(doc.uses)}
            overlap = len(query_stems & doc_stems)
            if overlap:
                results.append((doc, overlap))
        results.sort(key=lambda pair: pair[1], reverse=True)
        return results[:top_n]
