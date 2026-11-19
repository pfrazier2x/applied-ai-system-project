"""VibeFinder 2.0 web app.

Run locally:   streamlit run app.py
Deploy:        Streamlit Community Cloud -> point it at this repo, main file app.py

The app is a thin UI over the same VibeFinderAgent the CLI and tests use,
so everything shown here (trace, self-check, confidence) is the real
pipeline, not a mock-up.
"""

import html
import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src import llm  # noqa: E402
from src.agent import MAX_SCORE, VibeFinderAgent, setup_logging  # noqa: E402

FEEDBACK_FILE = ROOT / "logs" / "feedback.jsonl"

EXAMPLES = [
    "sad songs for a rainy night drive",
    "I need something for the gym, no pop",
    "something calm to fall asleep to",
    "chill lofi for studying, nothing too loud",
    "upbeat pop for a summer road trip",
    "jazz for a coffee shop, energy 0.4",
]

STAGES = [
    ("GUARD", "Guard", "Block empty, huge or injection input"),
    ("PARSE", "Parse", "Words → genre, mood, energy, “no X”"),
    ("VALIDATE", "Validate", "Can the catalog serve it?"),
    ("RETRIEVE", "Retrieve", "1.0 scorer + knowledge notes"),
    ("GENERATE", "Generate", "Reasons from retrieved facts only"),
    ("CHECK", "Check", "Real? Not excluded? Grounded?"),
    ("CONFIDENCE", "Confidence", "Understanding × match"),
]

GENRE_COLORS = {
    "lofi": "#7AA7FF", "pop": "#FF7AB6", "indie pop": "#FFB27A", "rock": "#FF6B6B",
    "ambient": "#8FE3CF", "jazz": "#F2C14E", "synthwave": "#B57CFF", "hip-hop": "#5ED3F3",
    "r&b": "#E58FFF", "edm": "#4DF0A0", "soul": "#F29E4C", "reggae": "#9BE15D", "folk": "#C9B38F",
}

st.set_page_config(page_title="VibeFinder 2.0", page_icon="🎧", layout="wide")

# --------------------------------------------------------------------------
# Styling
# --------------------------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;600&display=swap');
html, body, [class*="css"], .stMarkdown, p, li, label { font-family: 'Inter', sans-serif; }
h1, h2, h3, .vf-title { font-family: 'Space Grotesk', sans-serif !important; letter-spacing: -0.02em; }
.block-container { padding-top: 3.6rem; max-width: 1180px; }
.stButton button p, .stFormSubmitButton button p, .stDownloadButton button p {
  white-space: normal; overflow: visible; text-overflow: clip; line-height: 1.25; }
.stButton button, .stFormSubmitButton button { min-height: 2.6rem; height: auto; }
.vf-eyebrow { font-family: 'JetBrains Mono', monospace; color: #F2A541; font-size: .78rem;
  letter-spacing: .14em; text-transform: uppercase; font-weight: 600; }
.vf-title { font-size: 3rem; font-weight: 700; line-height: 1.05; margin: .2rem 0 .4rem; color: #F5F1E8; }
.vf-sub { color: #B8BDD6; font-size: 1.08rem; margin-bottom: 1.2rem; }
.vf-card { background: #1E2340; border: 1px solid #2B3156; border-radius: 16px; padding: 18px 20px;
  margin-bottom: 14px; }
.vf-song { display: flex; gap: 16px; align-items: flex-start; flex-wrap: wrap; }
.vf-song-main { flex: 1 1 260px; min-width: 0; }
.vf-song-stats { flex: 0 1 200px; min-width: 160px; }
.vf-rank { font-family: 'Space Grotesk', sans-serif; font-size: 1.9rem; font-weight: 700;
  color: #F2A541; min-width: 34px; line-height: 1; }
.vf-song-title { font-family: 'Space Grotesk', sans-serif; font-size: 1.25rem; font-weight: 700; color: #F5F1E8; }
.vf-artist { color: #B8BDD6; font-size: .95rem; }
.vf-tag { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: .75rem;
  font-weight: 600; margin: 6px 6px 0 0; background: #2B3156; color: #DDE1F5; }
.vf-reason { color: #C9CDE3; font-size: .92rem; margin-top: 10px; line-height: 1.45; }
.vf-bar-wrap { background: #151929; border-radius: 6px; height: 8px; width: 100%; overflow: hidden; }
.vf-bar { height: 8px; border-radius: 6px; }
.vf-meta { font-family: 'JetBrains Mono', monospace; font-size: .74rem; color: #8E94B5; margin-bottom: 3px; }
.vf-pill { display: inline-flex; gap: 6px; align-items: center; padding: 6px 12px; border-radius: 999px;
  background: #1E2340; border: 1px solid #2B3156; margin: 0 8px 8px 0; font-size: .88rem; }
.vf-pill b { color: #F2A541; font-weight: 600; }
.vf-pill i { color: #8E94B5; font-style: normal; font-size: .78rem; }
.vf-stages { display: grid; grid-template-columns: repeat(7, 1fr); gap: 8px; margin: 6px 0 14px; }
.vf-stage { background: #1E2340; border-radius: 12px; padding: 10px 10px 12px; border-top: 3px solid #3A4170;
  min-height: 92px; }
.vf-stage.ok { border-top-color: #7AA7FF; }
.vf-stage.warn { border-top-color: #F2A541; }
.vf-stage.bad { border-top-color: #FF6B6B; }
.vf-stage.skip { opacity: .4; }
.vf-stage-n { font-family: 'JetBrains Mono', monospace; font-size: .7rem; color: #7AA7FF; }
.vf-stage-t { font-weight: 600; font-size: .9rem; color: #F5F1E8; }
.vf-stage-d { font-size: .72rem; color: #9EA4C4; line-height: 1.3; margin-top: 2px; }
.vf-trace { font-family: 'JetBrains Mono', monospace; font-size: .8rem; background: #0E1120;
  border-radius: 12px; padding: 14px 16px; line-height: 1.7; white-space: pre-wrap; color: #C9CDE3; }
.vf-trace .f { color: #FF8A80; } .vf-trace .r { color: #7AA7FF; } .vf-trace .p { color: #8FE3A6; }
.vf-trace .s { color: #8E94B5; }
.vf-banner { border-radius: 14px; padding: 16px 18px; font-family: 'JetBrains Mono', monospace; font-size: .92rem; }
.vf-banner.blocked { background: #2A1620; color: #FF9A9A; border: 1px solid #5A2735; }
.vf-banner.clarify { background: #16213A; color: #9DBBFF; border: 1px solid #2B3F6E; }
.vf-big { font-family: 'Space Grotesk', sans-serif; font-size: clamp(1.5rem, 2.6vw, 2.6rem); white-space: nowrap; font-weight: 700; color: #F2A541; line-height: 1; }
.vf-big-l { color: #B8BDD6; font-size: .85rem; margin-top: 4px; }
div[data-testid="stMetricValue"] { font-family: 'Space Grotesk', sans-serif; color: #F2A541; }
@media (max-width: 900px) { .vf-stages { grid-template-columns: repeat(2, 1fr); } .vf-title { font-size: 2.2rem; } }
</style>
""", unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
@st.cache_resource
def get_agent(use_claude: bool) -> VibeFinderAgent:
    setup_logging()
    return VibeFinderAgent(use_claude=use_claude)


def esc(text) -> str:
    return html.escape(str(text))


def bar(value: float, color: str) -> str:
    pct = max(0.0, min(1.0, value)) * 100
    return (f'<div class="vf-bar-wrap"><div class="vf-bar" '
            f'style="width:{pct:.0f}%;background:{color}"></div></div>')


def stage_states(result) -> dict:
    """Map each pipeline stage to ok / warn / bad / skip from the trace."""
    states = {key: "skip" for key, _, _ in STAGES}
    for line in result.trace:
        for key, _, _ in STAGES:
            if line.startswith(key) or line.startswith(f"REPAIR") and key == "CHECK":
                if "blocked" in line or "still failing" in line:
                    states[key] = "bad"
                elif "failed" in line or line.startswith("REPAIR") or "asking" in line \
                        or "not in the catalog" in line:
                    states[key] = "warn" if states[key] != "bad" else "bad"
                elif states[key] == "skip":
                    states[key] = "ok"
    if result.status == "ok" and states["VALIDATE"] == "skip":
        states["VALIDATE"] = "ok"
    return states


def render_stages(result) -> None:
    states = stage_states(result)
    cells = []
    for i, (key, title, desc) in enumerate(STAGES, 1):
        cells.append(f'<div class="vf-stage {states[key]}"><div class="vf-stage-n">0{i}</div>'
                     f'<div class="vf-stage-t">{title}</div><div class="vf-stage-d">{desc}</div></div>')
    st.markdown(f'<div class="vf-stages">{"".join(cells)}</div>', unsafe_allow_html=True)


def render_trace(result) -> None:
    lines = []
    for step in result.trace:
        cls = ("f" if "failed" in step or "blocked" in step or "still failing" in step
               else "r" if step.startswith("REPAIR") or "re-ranked" in step or "energy limit" in step
               else "p" if step.startswith("CHECK passed")
               else "s" if step.strip().startswith("signal") else "")
        lines.append(f'<span class="{cls}">{esc(step)}</span>')
    st.markdown(f'<div class="vf-trace">{"<br>".join(lines)}</div>', unsafe_allow_html=True)


def render_understood(result) -> None:
    p = result.profile
    pills = [
        f'<span class="vf-pill">genre <b>{esc(p.genre or "any")}</b> <i>{esc(p.genre_source)}</i></span>',
        f'<span class="vf-pill">mood <b>{esc(p.mood or "any")}</b> <i>{esc(p.mood_source)}</i></span>',
        f'<span class="vf-pill">energy <b>{p.energy:.2f}</b>'
        + (f' <i>{esc(p.energy_mode)} limit</i>' if getattr(p, "energy_mode", None) else "") + "</span>",
    ]
    if p.excluded_genres:
        pills.append(f'<span class="vf-pill">excluding <b>{esc(", ".join(p.excluded_genres))}</b></span>')
    if getattr(p, "corrections", None):
        pills.append(f'<span class="vf-pill">typo fix <b>{esc(", ".join(p.corrections))}</b></span>')
    pills.append(f'<span class="vf-pill">parser <b>{esc(p.source)}</b></span>')
    st.markdown("".join(pills), unsafe_allow_html=True)


def render_song(i: int, rec: dict, key_prefix: str, request: str) -> None:
    color = GENRE_COLORS.get(rec["genre"], "#7AA7FF")
    st.markdown(f"""
<div class="vf-card"><div class="vf-song">
  <div class="vf-rank">{i}</div>
  <div class="vf-song-main">
    <div class="vf-song-title">{esc(rec['title'])}</div>
    <div class="vf-artist">{esc(rec['artist'])}</div>
    <span class="vf-tag" style="background:{color}22;color:{color}">{esc(rec['genre'])}</span>
    <span class="vf-tag">{esc(rec['mood'])}</span>
    <span class="vf-tag">{rec['tempo_bpm']:.0f} BPM</span>
    <div class="vf-reason">{esc(rec['reason'])}</div>
  </div>
  <div class="vf-song-stats">
    <div class="vf-meta">MATCH {rec['score']:.2f}/{MAX_SCORE:.0f}</div>{bar(rec['score'] / MAX_SCORE, '#F2A541')}
    <div class="vf-meta" style="margin-top:9px">ENERGY {rec['energy']:.2f}</div>{bar(rec['energy'], '#7AA7FF')}
    <div class="vf-meta" style="margin-top:9px">POSITIVITY {rec['valence']:.2f}</div>{bar(rec['valence'], '#8FE3CF')}
  </div>
</div></div>""", unsafe_allow_html=True)
    vote = st.feedback("thumbs", key=f"{key_prefix}-fb-{rec['id']}")
    if vote is not None:
        log_feedback(request, rec, vote)


def log_feedback(request: str, rec: dict, vote: int) -> None:
    """Stretch: store thumbs up/down so the weights can be tuned later."""
    key = (request, rec["id"], vote)
    logged = st.session_state.setdefault("logged_feedback", set())
    if key in logged:
        return
    logged.add(key)
    FEEDBACK_FILE.parent.mkdir(exist_ok=True)
    with FEEDBACK_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"),
                             "request": request, "song_id": rec["id"], "title": rec["title"],
                             "vote": "up" if vote == 1 else "down"}) + "\n")


def playlist_csv(result) -> bytes:
    rows = [{"rank": i, "title": r["title"], "artist": r["artist"], "genre": r["genre"],
             "mood": r["mood"], "energy": r["energy"], "score": round(r["score"], 2), "why": r["reason"]}
            for i, r in enumerate(result.recommendations, 1)]
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def render_result(result, key_prefix: str) -> None:
    if result.status == "blocked":
        render_stages(result)
        st.markdown(f'<div class="vf-banner blocked">BLOCKED: {esc(result.message)}</div>',
                    unsafe_allow_html=True)
        return
    if result.status == "needs_clarification":
        render_stages(result)
        st.markdown(f'<div class="vf-banner clarify">NEEDS_CLARIFICATION: {esc(result.message)}</div>',
                    unsafe_allow_html=True)
        with st.expander("Agent trace"):
            render_trace(result)
        return

    render_understood(result)
    render_stages(result)
    c1, c2, c3 = st.columns(3)
    c1.markdown(f'<div class="vf-card"><div class="vf-big">{result.confidence:.2f}</div>'
                f'<div class="vf-big-l">confidence · {esc(result.confidence_label)}</div>'
                f'<div style="margin-top:10px">{bar(result.confidence, "#F2A541")}</div></div>',
                unsafe_allow_html=True)
    check_color = "#8FE3A6" if result.check_passed else "#FF6B6B"
    c2.markdown(f'<div class="vf-card"><div class="vf-big" style="color:{check_color}">'
                f'{"PASSED" if result.check_passed else "FAILED"}</div>'
                f'<div class="vf-big-l">self-check · {result.repairs} repair(s)</div></div>',
                unsafe_allow_html=True)
    c3.markdown(f'<div class="vf-card"><div class="vf-big">{len(result.retrieved_notes)}</div>'
                f'<div class="vf-big-l">knowledge notes retrieved</div></div>', unsafe_allow_html=True)
    if result.message:
        st.warning(result.message)

    for i, rec in enumerate(result.recommendations, 1):
        render_song(i, rec, key_prefix, result.request)

    d1, d2 = st.columns([1, 3])
    d1.download_button("⬇ Download playlist (CSV)", playlist_csv(result),
                       file_name="vibefinder_playlist.csv", mime="text/csv",
                       key=f"{key_prefix}-dl", width="stretch")
    with st.expander("What it retrieved (RAG notes)"):
        for note in result.retrieved_notes:
            st.markdown(f"- {note}")
    with st.expander("Full agent trace", expanded=False):
        render_trace(result)


# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------
claude_ready = llm.claude_available()
with st.sidebar:
    st.markdown('<div class="vf-eyebrow">Settings</div>', unsafe_allow_html=True)
    k = st.slider("Songs to recommend", 1, 5, 3)
    use_claude = st.toggle("Use Claude for parsing + reasons", value=False, disabled=not claude_ready,
                           help=None if claude_ready else
                           "Set ANTHROPIC_API_KEY (and install anthropic) to enable. "
                           "Offline rules are the default and fully tested path.")
    st.caption("Mode: " + ("**Claude** (falls back to rules on any error)" if use_claude
                           else "**offline rules** · deterministic, no API key"))
    st.divider()
    history_box = st.container()

history = st.session_state.setdefault("history", [])


def render_history() -> None:
  with history_box:
    st.markdown('<div class="vf-eyebrow">History</div>', unsafe_allow_html=True)
    if not history:
        st.caption("Your requests show up here.")
    for item in reversed(history[-8:]):
        icon = {"ok": "🎵", "blocked": "⛔", "needs_clarification": "❓"}[item["status"]]
        if st.button(f"{icon} {item['request'][:38] or '(empty)'}", key=f"h-{item['time']}",
                     width="stretch"):
            st.session_state["query"] = item["request"]
            st.session_state["run_now"] = True
    if FEEDBACK_FILE.exists():
        votes = [json.loads(l) for l in FEEDBACK_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
        ups = sum(v["vote"] == "up" for v in votes)
        st.caption(f"Feedback logged: 👍 {ups} · 👎 {len(votes) - ups}")

agent = get_agent(use_claude)

# --------------------------------------------------------------------------
# Header
# --------------------------------------------------------------------------
st.markdown('<div class="vf-eyebrow">CodePath AI110 · Final project</div>'
            '<div class="vf-title">VibeFinder 2.0</div>'
            '<div class="vf-sub">A music recommender that retrieves before it answers, checks its own work, '
            'and tells you how sure it is.</div>', unsafe_allow_html=True)

tab_find, tab_lab, tab_eval, tab_catalog, tab_about = st.tabs(
    ["🎧 Find music", "🧪 Self-check lab", "📊 Reliability", "🗂 Catalog", "ℹ️ How it works"])

# --------------------------------------------------------------------------
# Find music
# --------------------------------------------------------------------------
with tab_find:
    # Example buttons fill the box and run on the next pass (a widget's value
    # can only be set before the widget is drawn).
    if "pending_query" in st.session_state:
        st.session_state["query"] = st.session_state.pop("pending_query")
        st.session_state["run_now"] = True
    with st.form("ask", border=False):
        cols = st.columns([4, 1.3], vertical_alignment="bottom")
        query = cols[0].text_input("What do you want to listen to?", key="query",
                                   placeholder="e.g. sad songs for a rainy night drive",
                                   label_visibility="collapsed")
        submitted = cols[1].form_submit_button("Find songs", type="primary", width="stretch")

    st.caption("Try one:")
    chip_cols = st.columns(3)
    for i, example in enumerate(EXAMPLES):
        if chip_cols[i % 3].button(example, key=f"ex-{i}", width="stretch"):
            st.session_state["pending_query"] = example
            st.rerun()

    run_now = st.session_state.pop("run_now", False)
    if submitted or run_now:
        result = agent.run(st.session_state.get("query", ""), k=k)
        st.session_state["last_result"] = result
        history.append({"request": result.request, "status": result.status,
                        "time": datetime.now().strftime("%H%M%S%f")})

    if "last_result" in st.session_state:
        st.write("")
        render_result(st.session_state["last_result"], "main")
    else:
        st.info("Describe a mood, an activity, a genre, or a genre to avoid. "
                "You don't need to name a genre: “gym” or “night drive” is enough.")

# --------------------------------------------------------------------------
# Self-check lab
# --------------------------------------------------------------------------
FAULTS = {
    "Invents song #999 + repeats a song": lambda c, k: [
        {"song_id": 999, "reason": "A song that does not exist"},
        {"song_id": c[0]["id"], "reason": "real"},
        {"song_id": c[0]["id"], "reason": "duplicate"}],
    "Gives reasons with no facts": lambda c, k: [
        {"song_id": s["id"], "reason": "trust me, it slaps"} for s in c[:k]],
    "Recommends a genre you excluded": None,  # built per-request below
    "Returns too few songs": lambda c, k: [
        {"song_id": c[0]["id"], "reason": f"{c[0]['genre']} pick"}],
}

with tab_lab:
    st.markdown("### Feed it a broken generator on purpose")
    st.caption("Swap the generator for a faulty fake model and watch the self-check catch it "
               "and repair the list from the retrieved candidates.")
    l1, l2 = st.columns([3, 2])
    lab_req = l1.text_input("Request", "happy edm for a party, no pop", key="lab_req")
    fault = l2.selectbox("Fault to inject", list(FAULTS))
    if st.button("Run with fault", type="primary"):
        if fault == "Recommends a genre you excluded":
            pop_ids = [s["id"] for s in agent.songs if s["genre"] == "pop"][:k]
            agent.generator_override = lambda c, k_: [
                {"song_id": sid, "reason": "pop banger"} for sid in pop_ids[:k_]]
        else:
            agent.generator_override = FAULTS[fault]
        try:
            st.session_state["lab_result"] = agent.run(lab_req, k=k)
        finally:
            agent.generator_override = None
    if "lab_result" in st.session_state:
        res = st.session_state["lab_result"]
        if res.status == "ok":
            render_trace(res)
            st.write("")
            st.markdown("**What the user sees after repair:**")
            for i, rec in enumerate(res.recommendations, 1):
                render_song(i, rec, "lab", res.request)
        else:
            render_result(res, "lab")

# --------------------------------------------------------------------------
# Reliability
# --------------------------------------------------------------------------
with tab_eval:
    st.markdown("### Testing it like I don't trust it")
    st.caption("Runs the 13 written evaluation cases live against the current catalog "
               "(same as `python -m scripts.evaluate --offline`).")
    if st.button("Run evaluation", type="primary"):
        from scripts.evaluate import CASES, evaluate_case
        eval_agent = VibeFinderAgent(use_claude=False)
        st.session_state["eval_rows"] = [evaluate_case(eval_agent, c) for c in CASES]
    rows = st.session_state.get("eval_rows")
    if rows:
        passed = sum(r["passed"] for r in rows)
        confs = [r["confidence"] for r in rows if r["confidence"] is not None]
        m1, m2, m3 = st.columns(3)
        m1.metric("Evaluation cases passed", f"{passed}/{len(rows)}")
        m2.metric("Average confidence", f"{(sum(confs) / len(confs) if confs else 0):.2f}")
        m3.metric("Guardrail cases", f"{sum(r['status'] != 'ok' for r in rows)}")
        df = pd.DataFrame([{"#": i, "Result": "✅ Pass" if r["passed"] else "❌ " + "; ".join(r["failures"]),
                            "Input": r["request"] or "(empty)", "Criteria": r["criteria"],
                            "Picks / status": ", ".join(r["picks"]) or r["status"],
                            "Conf.": r["confidence"]} for i, r in enumerate(rows, 1)])
        st.dataframe(df, hide_index=True, width="stretch")
    else:
        saved = ROOT / "logs" / "eval_report.md"
        if saved.exists():
            with st.expander("Last saved report (logs/eval_report.md)"):
                st.markdown(saved.read_text(encoding="utf-8"))

# --------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------
with tab_catalog:
    songs_df = pd.DataFrame(agent.songs)
    st.markdown(f"### {len(songs_df)} songs · {songs_df['genre'].nunique()} genres · "
                f"{songs_df['mood'].nunique()} moods")
    f1, f2, f3 = st.columns(3)
    genres = f1.multiselect("Genre", sorted(songs_df["genre"].unique()))
    moods = f2.multiselect("Mood", sorted(songs_df["mood"].unique()))
    lo, hi = f3.slider("Energy", 0.0, 1.0, (0.0, 1.0), 0.05)
    view = songs_df[songs_df["energy"].between(lo, hi)]
    if genres:
        view = view[view["genre"].isin(genres)]
    if moods:
        view = view[view["mood"].isin(moods)]
    st.scatter_chart(view, x="energy", y="valence", color="genre", size=80, height=360)
    st.dataframe(view[["title", "artist", "genre", "mood", "energy", "tempo_bpm", "valence",
                       "danceability", "acousticness"]], hide_index=True, width="stretch")

# --------------------------------------------------------------------------
# About
# --------------------------------------------------------------------------
with tab_about:
    st.markdown("### How a request flows")
    st.markdown('<div class="vf-stages">' + "".join(
        f'<div class="vf-stage ok"><div class="vf-stage-n">0{i}</div><div class="vf-stage-t">{t}</div>'
        f'<div class="vf-stage-d">{d}</div></div>' for i, (_, t, d) in enumerate(STAGES, 1))
        + "</div>", unsafe_allow_html=True)
    st.markdown("""
Every step is written to `logs/vibefinder.log`. Claude can do steps 2 and 5 if an API key is set;
otherwise it runs fully offline.

**Added in this version (stretch features)**
- **Energy limits.** “Fall asleep”, “bedtime” or “hype” now act as a hard energy limit, so a mood match
  can't pull in a song that's too energetic. This fixed the one evaluation case 2.0 left failing.
- **Bigger catalog.** 60 songs (up from 20), at least 4 per genre, so top-5 lists are more varied.
- **Typo-tolerant parsing.** “chil jazzz”, “ambiant” and “raggae” are corrected and shown as a signal.
  Words the knowledge base uses (like “reading”) are never “corrected”.
- **Artist variety.** At most one song per artist in the candidates, when the catalog allows it.
- **Web app.** This UI: live pipeline view, self-check lab, live evaluation, catalog explorer,
  playlist download, and 👍/👎 feedback saved to `logs/feedback.jsonl`.
""")

render_history()
