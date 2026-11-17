"""Command-line entry point for VibeFinder 2.0.

Examples:
    python -m src.vibefinder "chill lofi for studying"
    python -m src.vibefinder "something for the gym, no pop" --k 5 --trace
    python -m src.vibefinder            # interactive mode
"""

import argparse
import sys

from src.agent import AgentResult, VibeFinderAgent, setup_logging


def format_result(result: AgentResult, show_trace: bool = False) -> str:
    lines = [f'Request: "{result.request}"']
    if result.status != "ok":
        lines.append(f"Status: {result.status.upper()} - {result.message}")
    else:
        p = result.profile
        lines.append(f"Understood: genre={p.genre} ({p.genre_source}), mood={p.mood}, "
                     f"energy={p.energy:.2f}"
                     + (f", excluding {', '.join(p.excluded_genres)}" if p.excluded_genres else "")
                     + f"  [parser: {p.source}]")
        lines.append("")
        for i, rec in enumerate(result.recommendations, 1):
            lines.append(f"  {i}. {rec['title']} - {rec['artist']}  (score {rec['score']:.2f}/4)")
            lines.append(f"     Why: {rec['reason']}")
        lines.append("")
        lines.append(f"Self-check: {'PASSED' if result.check_passed else 'FAILED'}"
                     f" (repairs: {result.repairs})")
        lines.append(f"Confidence: {result.confidence:.2f} ({result.confidence_label})")
        if result.message:
            lines.append(f"Note: {result.message}")
    if show_trace:
        lines.append("")
        lines.append("Agent trace:")
        lines.extend(f"  - {step}" for step in result.trace)
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="VibeFinder 2.0 - music recommendations from plain English")
    parser.add_argument("request", nargs="?", help="what you want to listen to")
    parser.add_argument("--k", type=int, default=3, help="number of songs (1-5)")
    parser.add_argument("--trace", action="store_true", help="print every agent step")
    parser.add_argument("--offline", action="store_true", help="never call Claude, even if a key is set")
    args = parser.parse_args(argv)

    if not 1 <= args.k <= 5:
        print("--k must be between 1 and 5")
        return 2

    setup_logging()
    agent = VibeFinderAgent(use_claude=False if args.offline else None)
    print(f"VibeFinder 2.0 | {len(agent.songs)} songs | "
          f"language model: {'Claude' if agent.use_claude else 'offline rules'}\n")

    if args.request is not None:
        print(format_result(agent.run(args.request, k=args.k), args.trace))
        return 0

    print("Type a request (blank line to quit).")
    while True:
        try:
            text = input("\n> ").strip()
        except EOFError:
            break
        if not text:
            break
        print(format_result(agent.run(text, k=args.k), args.trace))
    return 0


if __name__ == "__main__":
    sys.exit(main())
