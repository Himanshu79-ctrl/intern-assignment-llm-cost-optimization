"""
Per-call cost breakdown for the submission.

Run from the repo root:
    python scripts/cost_report.py q1 T-1001
    python scripts/cost_report.py q2 T-1001 T-1002
    python scripts/cost_report.py q2 T-1001 --no-shortlist   # experiment: send all ids

Points per call are taken from CostSession.total_points() deltas, so they are
the authoritative billed numbers, not my own arithmetic.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.tokens import count_tokens  # noqa: E402


def _instrument(session, rows: list[dict]) -> None:
    original = session.record

    def record(label, prompt, completion, cached_prefix_tokens=0, *args, **kwargs):
        before = session.total_points()
        result = original(label, prompt, completion, cached_prefix_tokens, *args, **kwargs)
        after = session.total_points()
        total_in = count_tokens(prompt)
        rows.append(
            {
                "call": label,
                "uncached_in": total_in - cached_prefix_tokens,
                "cached_in": cached_prefix_tokens,
                "out": count_tokens(completion),
                "points": round(after - before, 2),
            }
        )
        return result

    session.record = record


def _make(track: str, no_shortlist: bool):
    if track == "q1":
        from question1.agent import SupportCopilot

        return SupportCopilot()
    from question2.agent import SupportPipeline

    pipe = SupportPipeline()
    if no_shortlist:
        pipe._retrieve = lambda signals: list(pipe.ids)
    return pipe


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    no_shortlist = "--no-shortlist" in sys.argv
    if len(args) < 2 or args[0] not in {"q1", "q2"}:
        sys.exit(__doc__)
    track, tickets = args[0], args[1:]

    for tid in tickets:
        agent = _make(track, no_shortlist)
        rows: list[dict] = []
        _instrument(agent.session, rows)
        result = agent.handle_ticket(tid)

        print(f"\n### {track.upper()} {tid} -> {result.action} / {result.kb_article}")
        print("| Call | Uncached in | Cached in | Out | Points |")
        print("|---|---|---|---|---|")
        for r in rows:
            print(
                f"| {r['call']} | {r['uncached_in']} | {r['cached_in']} "
                f"| {r['out']} | {r['points']} |"
            )
        print(f"| **total** | | | | **{agent.session.total_points()}** |")


if __name__ == "__main__":
    main()