from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.billing import CostSession  # noqa: E402
from shared.kb import all_articles_blob, article_ids  # noqa: E402
from shared.llm import ChatMessage, LlmClient  # noqa: E402
from shared.tools import format_thread, get_order, get_ticket  # noqa: E402

PUBLIC = ["T-1001", "T-1002", "T-1003", "T-1004"]

STEPS = [
    ("0. reconstructed baseline", dict(uuid_line=True, verbose=True, full_kb=True, compact=False)),
    ("1. + remove uuid line", dict(uuid_line=False, verbose=True, full_kb=True, compact=False)),
    ("2. + remove verbose phrases", dict(uuid_line=False, verbose=False, full_kb=True, compact=False)),
    ("3. + article ids instead of full KB", dict(uuid_line=False, verbose=False, full_kb=False, compact=False)),
    ("4. + compact snapshot, JSON-only", dict(uuid_line=False, verbose=False, full_kb=False, compact=True)),
]


def build_messages(tid: str, *, uuid_line: bool, verbose: bool, full_kb: bool, compact: bool):
    ticket = get_ticket(tid)
    order = get_order(ticket["order_id"])
    thread = format_thread(ticket)

    parts = []
    if uuid_line:
        parts.append(f"Run id {uuid.uuid4()}")
    parts.append("You are ShopAssist Tier-1 support. Choose an action and the KB article that backs it.")
    if verbose:
        parts.append("Think step by step. Write full reasoning and quote the article you use.")
    if full_kb:
        parts.append("HELP CENTER:\n" + all_articles_blob())
    else:
        parts.append("ARTICLE IDS: " + ", ".join(article_ids()))
    if compact:
        parts.append('Output only JSON: {"action":"...","kb_article":"..."}')
    else:
        parts.append("Return JSON with action, kb_article and customer_reply.")

    snapshot = json.dumps(order, separators=(",", ":")) if compact else json.dumps(order, indent=2)
    user = f"{tid}\nTHREAD:\n{thread}\nORDER_SNAPSHOT:\n{snapshot}\nEND_SNAPSHOT"
    return [ChatMessage("system", "\n".join(parts)), ChatMessage("user", user)]


def points_for(tid: str, **flags) -> float:
    session = CostSession()
    LlmClient(session).chat("ablation", build_messages(tid, **flags))
    return session.total_points()


def main() -> None:
    print("| Step | T-1001 points | Avg of 4 public tickets |")
    print("|---|---|---|")
    for name, flags in STEPS:
        first = points_for(PUBLIC[0], **flags)
        avg = sum(points_for(t, **flags) for t in PUBLIC) / len(PUBLIC)
        print(f"| {name} | {first:.0f} | {avg:.0f} |")


if __name__ == "__main__":
    main()