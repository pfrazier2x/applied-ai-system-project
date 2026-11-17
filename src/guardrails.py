"""Guardrails: checks that run before and after the AI steps.

- validate_input:   rejects empty, oversized, or prompt-injection input.
- validate_profile: clamps energy and drops genres/moods the catalog lacks.
- check_recommendations: the agent's self-check. Every recommended song
  must exist in the catalog, must come from the retrieved candidates,
  must not be a genre the user excluded, and must not repeat.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List

MAX_INPUT_CHARS = 300

INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above) (instructions|rules)",
    r"system prompt",
    r"you are now",
    r"developer mode",
    r"reveal (your|the) (prompt|instructions)",
]


class GuardrailError(ValueError):
    """Raised when input should not be processed at all."""


@dataclass
class CheckResult:
    ok: bool
    issues: List[str] = field(default_factory=list)


def validate_input(text: str) -> str:
    """Return cleaned text or raise GuardrailError with a user-safe message."""
    if text is None or not str(text).strip():
        raise GuardrailError("Empty request. Try something like 'chill music for studying'.")
    cleaned = " ".join(str(text).split())
    if len(cleaned) > MAX_INPUT_CHARS:
        raise GuardrailError(
            f"Request is {len(cleaned)} characters; the limit is {MAX_INPUT_CHARS}."
        )
    lowered = cleaned.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, lowered):
            raise GuardrailError("Request looks like an instruction to the system, not a music request.")
    return cleaned


def validate_profile(parsed, known_genres: Iterable[str], known_moods: Iterable[str]) -> List[str]:
    """Fix the parsed profile in place; return warnings describing each fix."""
    warnings = []
    genres, moods = set(known_genres), set(known_moods)
    if parsed.genre and parsed.genre not in genres:
        warnings.append(f"genre '{parsed.genre}' is not in the catalog; ignoring it")
        parsed.genre, parsed.genre_source = None, "none"
    if parsed.mood and parsed.mood not in moods:
        warnings.append(f"mood '{parsed.mood}' is not in the catalog; ignoring it")
        parsed.mood, parsed.mood_source = None, "none"
    if not 0.0 <= parsed.energy <= 1.0:
        clamped = min(1.0, max(0.0, parsed.energy))
        warnings.append(f"energy {parsed.energy} out of range; clamped to {clamped}")
        parsed.energy = clamped
    if parsed.genre and parsed.genre in parsed.excluded_genres:
        warnings.append(f"genre '{parsed.genre}' was both requested and excluded; dropping it")
        parsed.genre, parsed.genre_source = None, "none"
    return warnings


def check_recommendations(recs: List[Dict], catalog: Dict[int, Dict],
                          candidate_ids: Iterable[int],
                          excluded_genres: Iterable[str], k: int) -> CheckResult:
    """Self-check run on the generator's output before it is shown."""
    issues = []
    candidates = set(candidate_ids)
    excluded = set(excluded_genres)
    seen = set()
    for rec in recs:
        song_id = rec.get("song_id")
        if song_id not in catalog:
            issues.append(f"song_id {song_id} does not exist in the catalog (hallucinated)")
            continue
        if song_id not in candidates:
            issues.append(f"song_id {song_id} was not in the retrieved candidates")
        if catalog[song_id]["genre"] in excluded:
            issues.append(f"'{catalog[song_id]['title']}' is an excluded genre ({catalog[song_id]['genre']})")
        if song_id in seen:
            issues.append(f"song_id {song_id} recommended twice")
        seen.add(song_id)
        if not str(rec.get("reason", "")).strip():
            issues.append(f"song_id {song_id} has no explanation")
    if len(recs) != k:
        issues.append(f"expected {k} recommendations, got {len(recs)}")
    return CheckResult(ok=not issues, issues=issues)
