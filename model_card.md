# 🎧 Model Card: VibeFinder 2.0

## 1. Model overview

**Name:** VibeFinder 2.0, a music recommender agent with retrieval, self-checks and guardrails.
**Base project:** VibeFinder 1.0 (CodePath AI110 Module 3, Music Recommender Simulation). The original model card is in [`docs/vibefinder-1.0-model_card.md`](docs/vibefinder-1.0-model_card.md).

**What it does:** Takes a plain-English music request and returns *k* songs from a 20-song catalog, each with an explanation grounded in a small knowledge base, plus a confidence score.

**How it works:** The agent runs seven steps: guard → parse → validate → retrieve → generate → self-check/repair → confidence. Retrieval uses the unchanged VibeFinder 1.0 scorer (genre +2, mood +1, energy similarity up to +1) and keyword matching over 19 genre/mood notes. The default mode is fully offline and deterministic. With an API key, Claude can handle parsing and explanation writing, but it is limited to the retrieved candidates and the same self-check.

**Intended use:** A classroom and portfolio demonstration of trustworthy AI-system design: retrieval, self-checking, guardrails and evaluation. It is not a production music service.

## 2. Data

- `data/songs.csv`: 20 fictional songs, 13 genres, 6 moods, with energy, tempo, valence, danceability and acousticness. Most genres have only 1-3 songs.
- `data/knowledge/genres.md`, `moods.md`: short notes I wrote describing typical uses and energy for each genre and mood. They reflect my own judgment, not a measured dataset.

## 3. Evaluation results

- **24/24** unit tests pass (`logs/pytest_output.txt`).
- **12/13** evaluation cases pass (`logs/eval_report.md`). Average confidence on answered requests: **0.79**.
- The self-check caught **every** injected fault in testing: an invented song ID, a duplicate, and an ungrounded explanation.
- Known failure: for "something calm to fall asleep to", one of three picks has energy 0.42, above the 0.4 limit (see Limitations).

## 4. Limitations and biases

- **Tiny, uneven catalog.** 20 songs means some genres have a single song. Asking for "reggae" can only ever surface one real match, and the rest of the list is filled from other genres. Confidence scores are lower then, but the user still gets songs they didn't ask for.
- **Inherited weighting bias.** The 1.0 scorer lets a genre match (+2) or mood match (+1) outweigh energy (max +1). In evaluation case 5, a 0.42-energy *chill* lofi song beat a 0.25-energy *relaxed* folk song for a sleep request. Users who care most about energy or tempo are underserved.
- **The knowledge base reflects my taste and culture.** Notes like "jazz: coffee shops" or "hip-hop: workouts" are stereotypes I wrote. They steer which genre gets inferred for an activity, so they can reinforce narrow associations (for example, never suggesting folk for working out).
- **English keyword parsing.** The offline parser only knows the words in its synonym tables. Slang, other languages, typos ("lofy") and unusual phrasing fall through. "k-pop" gets read as "pop", and genres the catalog lacks, like classical, get a clarifying question rather than a real answer.
- **Confidence is a heuristic, not a probability.** It combines "how much of the request was understood" with "how well the songs scored". It was not calibrated against real user satisfaction.
- **The Claude path is untested in recorded evidence.** I had no API key, so every logged result comes from the offline path. The fallback and the self-check are designed to protect that path, but its output quality has not been measured.

## 5. Misuse and how it is prevented

The stakes are low, since it's a song recommender, but the system could still be misused:

- **Prompt injection / using it as a general chatbot.** Inputs containing phrases like "ignore previous instructions" or "system prompt" are blocked before any model sees them. In Claude mode, the system prompt tells the model to treat the request as data, and Claude can only output a structured profile or picks from the candidate list. It cannot return free-form text to the user.
- **Hallucinated or fabricated content.** The self-check rejects any song not in the catalog and retrieved pool, and any explanation that doesn't name the song's real genre or mood.
- **Resource abuse.** Input is capped at 300 characters and `--k` at 5, and each request makes at most two model calls.
- **What it doesn't prevent:** the keyword blocklist can be bypassed with rephrasing. If the catalog were real, someone could also try to use the recommender to promote particular artists by editing the knowledge notes. Requiring review of knowledge-base changes (they are plain files under version control) is the mitigation.

## 6. What surprised me while testing reliability

- **The demo looked fine while the test failed.** "Something calm to fall asleep to" returned reasonable-looking chill songs, so I would have called it working. Only the written criteria (genre should be *inferred as ambient*, energy ≤ 0.4) showed that retrieval had silently found nothing, because the notes say "sleep" and the user typed "asleep".
- **Fixing retrieval didn't fully fix the case.** After the query-expansion fix, ambient was retrieved correctly, but the old 1.0 weights still let a higher-energy song in. A bug in one layer can hide a bug in another.
- **My own self-check had a hole.** When I first ran the hallucination demo, the check caught the invented song and the duplicate but let the explanation "real" through, because it only checked that a reason was non-empty. I added the grounding rule after seeing that.
- **Confidence moved in the right direction for unseen genres.** "k-pop" scored 0.64 (medium) and "classical" triggered a clarifying question, rather than producing confident nonsense.

## 7. Collaboration with AI during this project

I built this with Claude (in Claude Code) as a pair programmer. I chose the base project and goals, ran and read every output, and decided what to keep. Claude drafted most of the module code, the tests and the documentation structure. I reviewed it against the actual run logs.

**A suggestion I accepted:** Claude suggested making the self-check *restrict the generator to the retrieved candidate songs* instead of trying to detect bad songs after the fact. I accepted it because it turns "the model might hallucinate a song" into a rule the code enforces, whether the generator is a template or an LLM. The evaluation's injected-fault case (13) shows it working.

**A suggestion I did not accept as written:** Claude's first plan made the Claude API the main path for parsing and explanations, with offline rules only as an emergency fallback. I didn't have an API key, and I wanted anyone grading or cloning the repo to get the same results I did. So I had it flipped: offline rules + retrieval became the default, fully tested path, and Claude became optional. The trade-off is less natural-sounding explanations, but the project is reproducible and every logged result can be regenerated with no account or cost.

**Something I revised after review:** an AI-drafted README line claimed the first evaluation run scored 11/13. When I checked `logs/eval_report_before_fix.md`, it was actually 12/13, with case 5 failing on three criteria instead of one. I corrected it. AI-written summaries of test results still have to be checked against the real logs.

## 8. Future improvements

- Re-weight or learn the scoring weights so energy can override a mood match for sleep and focus requests, then re-run the evaluation.
- Replace keyword retrieval with embeddings so synonyms don't need a hand-written table.
- Expand the catalog so each genre has enough songs for diverse top-5 lists.
- Run the evaluation in Claude mode and compare parse accuracy against the rules path.
