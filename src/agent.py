"""VibeFinder 2.0 agent: plan -> retrieve -> generate -> self-check -> answer.

Pipeline for one request:

  1. GUARD     validate_input rejects empty / huge / injection text.
  2. PARSE     request -> profile (Claude if available, else rules + KB retrieval).
  3. VALIDATE  validate_profile fixes or drops anything the catalog can't serve.
               If neither a genre nor a mood was understood, ask a clarifying
               question instead of guessing.
  4. RETRIEVE  the original VibeFinder 1.0 scorer ranks the catalog (minus
               excluded genres) -> candidate songs; KB notes for the genre/mood.
  5. GENERATE  pick k songs + reasons grounded in the retrieved notes.
  6. CHECK     check_recommendations; if it fails, repair from candidates and
               check again (at most MAX_REPAIRS times).
  7. SCORE     confidence = how well the request was understood x how well
               the songs matched.

Every step is appended to `trace` and written to logs/vibefinder.log.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from src import llm
from src.guardrails import (GuardrailError, check_recommendations, is_grounded,
                            validate_input, validate_profile)
from src.knowledge_base import KnowledgeBase
from src.parser import ParsedRequest, parse_request
from src.recommender import load_songs, recommend_songs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SONGS_CSV = PROJECT_ROOT / "data" / "songs.csv"
LOG_FILE = PROJECT_ROOT / "logs" / "vibefinder.log"

MAX_SCORE = 4.0          # genre 2 + mood 1 + energy 1 (VibeFinder 1.0 weights)
MAX_REPAIRS = 2
CANDIDATE_POOL = 6

logger = logging.getLogger("vibefinder")

ENERGY_LIMIT_MARGIN = 0.1     # "low" cue: energy <= target + margin
ENERGY_FLOOR_MARGIN = 0.15    # "high" cue: energy >= target - margin


def apply_energy_limit(songs: List[Dict], profile) -> List[Dict]:
    """Keep only songs inside the energy limit implied by a strong cue."""
    mode = getattr(profile, "energy_mode", None)
    if mode == "low":
        return [s for s in songs if s["energy"] <= profile.energy + ENERGY_LIMIT_MARGIN]
    if mode == "high":
        return [s for s in songs if s["energy"] >= profile.energy - ENERGY_FLOOR_MARGIN]
    return list(songs)


def diversify(ranked: List[Dict], n: int) -> List[Dict]:
    """Take the best n songs with at most one per artist, keeping score order.

    Falls back to repeat artists only if there aren't enough distinct ones.
    """
    picked, seen, leftovers = [], set(), []
    for song in ranked:
        if song["artist"] in seen:
            leftovers.append(song)
        else:
            picked.append(song)
            seen.add(song["artist"])
    picked = sorted(picked[:n], key=lambda s: s["score"], reverse=True)
    if len(picked) < n:
        picked.extend(leftovers[: n - len(picked)])
    return picked


def setup_logging(verbose: bool = False) -> None:
    """Log every run to logs/vibefinder.log; echo to console only if verbose."""
    if logger.handlers:
        return
    LOG_FILE.parent.mkdir(exist_ok=True)
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(file_handler)
    if verbose:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("  [log] %(message)s"))
        logger.addHandler(console)


@dataclass
class AgentResult:
    status: str                              # "ok" | "blocked" | "needs_clarification"
    request: str
    message: str = ""
    profile: Optional[ParsedRequest] = None
    recommendations: List[Dict] = field(default_factory=list)
    confidence: float = 0.0
    confidence_label: str = "n/a"
    retrieved_notes: List[str] = field(default_factory=list)
    trace: List[str] = field(default_factory=list)
    check_passed: bool = False
    repairs: int = 0


class VibeFinderAgent:
    def __init__(self, songs: Optional[List[Dict]] = None,
                 kb: Optional[KnowledgeBase] = None, use_claude: Optional[bool] = None):
        self.songs = songs if songs is not None else load_songs(str(SONGS_CSV))
        self.catalog = {s["id"]: s for s in self.songs}
        self.kb = kb or KnowledgeBase.load()
        self.genres = sorted({s["genre"] for s in self.songs})
        self.moods = sorted({s["mood"] for s in self.songs})
        self.use_claude = llm.claude_available() if use_claude is None else use_claude
        # Hook used by tests/evaluation to simulate a faulty generator.
        self.generator_override = None

    # ---- helpers -------------------------------------------------------
    def _step(self, result: AgentResult, text: str) -> None:
        result.trace.append(text)
        logger.info("%s | %s", result.request[:40], text)

    def _template_reason(self, song: Dict, profile: ParsedRequest) -> str:
        parts = [f"{song['genre']} / {song['mood']}, energy {song['energy']:.2f} "
                 f"(target {profile.energy:.2f})"]
        genre_doc = self.kb.get("genre", song["genre"])
        mood_doc = self.kb.get("mood", song["mood"])
        if genre_doc and genre_doc.uses:
            parts.append(f"{song['genre']} is commonly used for {genre_doc.uses.lower()}")
        if mood_doc and mood_doc.uses:
            parts.append(f"{song['mood']} songs are good for {mood_doc.uses.lower()}")
        return "; ".join(parts) + "."

    def _confidence(self, profile: ParsedRequest, picks: List[Dict], repairs: int) -> float:
        understanding = (
            0.6 * {"stated": 1.0, "inferred": 0.7}.get(profile.genre_source, 0.3)
            + 0.4 * (1.0 if profile.mood_source == "stated" else 0.4)
        )
        match = sum(p["score"] for p in picks) / (len(picks) * MAX_SCORE) if picks else 0.0
        value = 0.5 * understanding + 0.5 * match - 0.1 * repairs
        return round(max(0.0, min(1.0, value)), 2)

    # ---- main loop -----------------------------------------------------
    def run(self, text: str, k: int = 3) -> AgentResult:
        result = AgentResult(status="ok", request=str(text or ""))

        # 1. GUARD
        try:
            cleaned = validate_input(text)
        except GuardrailError as error:
            result.status, result.message = "blocked", str(error)
            self._step(result, f"GUARD blocked input: {error}")
            return result
        self._step(result, "GUARD input accepted")

        # 2. PARSE
        profile = None
        if self.use_claude:
            out = llm.claude_parse_request(cleaned, self.genres, self.moods)
            if out is not None:
                profile = ParsedRequest(
                    genre=out.genre, mood=out.mood, energy=out.energy,
                    excluded_genres=out.excluded_genres,
                    genre_source="stated" if out.genre else "none",
                    mood_source="stated" if out.mood else "none",
                    signals=["parsed by Claude"], source="claude")
            else:
                self._step(result, "PARSE Claude unavailable -> falling back to rules")
        if profile is None:
            profile = parse_request(cleaned, self.kb)
        result.profile = profile
        self._step(result, f"PARSE ({profile.source}) genre={profile.genre} "
                           f"mood={profile.mood} energy={profile.energy:.2f} "
                           f"excluded={profile.excluded_genres}")
        for signal in profile.signals:
            self._step(result, f"  signal: {signal}")

        # 3. VALIDATE
        for warning in validate_profile(profile, self.genres, self.moods):
            self._step(result, f"VALIDATE {warning}")
        if profile.genre is None and profile.mood is None:
            result.status = "needs_clarification"
            result.message = ("I couldn't find a genre, mood, or activity in that request. "
                              "Try e.g. 'upbeat pop for a road trip' or 'calm music for reading'.")
            self._step(result, "VALIDATE nothing understood -> asking for clarification")
            return result

        # 4. RETRIEVE
        pool = [s for s in self.songs if s["genre"] not in profile.excluded_genres]
        # Stretch: a strong energy cue ("fall asleep", "hype") becomes a hard
        # limit, so a mood match can no longer pull in a song that is too
        # energetic (the documented failing case 5 in VibeFinder 2.0).
        limited = apply_energy_limit(pool, profile)
        if len(limited) >= k:
            if len(limited) < len(pool):
                self._step(result, f"RETRIEVE energy limit ({profile.energy_mode}) kept "
                                   f"{len(limited)}/{len(pool)} songs")
            pool = limited
        elif profile.energy_mode:
            self._step(result, "RETRIEVE energy limit skipped: too few songs would remain")
        ranked = recommend_songs(profile.as_prefs(), pool, k=len(pool))
        candidates = diversify([{**song, "score": score} for song, score, _ in ranked],
                               max(CANDIDATE_POOL, k * 2))
        if [c["id"] for c in candidates] != [s["id"] for s, _, _ in ranked[:len(candidates)]]:
            self._step(result, "RETRIEVE re-ranked for variety (max one song per artist)")
        notes = []
        for kind, name in (("genre", profile.genre), ("mood", profile.mood)):
            doc = self.kb.get(kind, name)
            if doc:
                notes.append(f"[{kind}: {doc.name}] {doc.text}")
        result.retrieved_notes = notes
        self._step(result, f"RETRIEVE {len(candidates)} candidates "
                           f"{[c['id'] for c in candidates]}, {len(notes)} knowledge notes")

        # 5. GENERATE
        if self.generator_override is not None:
            picks = self.generator_override(candidates, k)
            self._step(result, "GENERATE using override generator")
        elif self.use_claude:
            slim = [{k_: c[k_] for k_ in ("id", "title", "artist", "genre", "mood", "energy", "score")}
                    for c in candidates]
            picks = llm.claude_explain(cleaned, slim, notes, k)
            if picks is None:
                self._step(result, "GENERATE Claude failed -> template explanations")
        else:
            picks = None
        if picks is None:
            picks = [{"song_id": c["id"], "reason": self._template_reason(c, profile)}
                     for c in candidates[:k]]
            self._step(result, "GENERATE grounded template explanations")

        # 6. SELF-CHECK + REPAIR
        candidate_ids = [c["id"] for c in candidates]
        check = check_recommendations(picks, self.catalog, candidate_ids,
                                      profile.excluded_genres, k)
        while not check.ok and result.repairs < MAX_REPAIRS:
            result.repairs += 1
            for issue in check.issues:
                self._step(result, f"CHECK failed: {issue}")
            valid, used = [], set()
            for p in picks:
                sid = p.get("song_id")
                if (sid in candidate_ids and sid not in used
                        and is_grounded(p.get("reason", ""), self.catalog[sid])
                        and self.catalog[sid]["genre"] not in profile.excluded_genres):
                    valid.append(p)
                    used.add(sid)
            for c in candidates:
                if len(valid) >= k:
                    break
                if c["id"] not in used:
                    valid.append({"song_id": c["id"], "reason": self._template_reason(c, profile)})
                    used.add(c["id"])
            picks = valid[:k]
            self._step(result, f"REPAIR #{result.repairs}: rebuilt list from retrieved candidates")
            check = check_recommendations(picks, self.catalog, candidate_ids,
                                          profile.excluded_genres, k)
        result.check_passed = check.ok
        self._step(result, "CHECK passed" if check.ok else f"CHECK still failing: {check.issues}")

        scores = {c["id"]: c["score"] for c in candidates}
        result.recommendations = [
            {**self.catalog[p["song_id"]], "score": scores.get(p["song_id"], 0.0),
             "reason": p["reason"]}
            for p in picks if p["song_id"] in self.catalog
        ]

        # 7. CONFIDENCE
        result.confidence = self._confidence(profile, result.recommendations, result.repairs)
        result.confidence_label = ("high" if result.confidence >= 0.75
                                   else "medium" if result.confidence >= 0.5 else "low")
        if result.confidence_label == "low":
            result.message = "Low confidence: the catalog has few close matches for this request."
        self._step(result, f"CONFIDENCE {result.confidence:.2f} ({result.confidence_label})")
        return result
