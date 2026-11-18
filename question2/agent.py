from __future__ import annotations

import json
import re
from dataclasses import dataclass

from shared.billing import CostSession
from shared.kb import article_ids
from shared.llm import ChatMessage, LlmClient
from shared.tools import format_thread, get_order, get_ticket

from question1.agent import (
    _MAX_THREAD_CHARS,
    compact_snapshot,
    parse_resolution,
    scrub,
)

VALID_ACTIONS = {"REFUND", "REPLACE", "SEND_ARTICLE", "ESCALATE_TIER2"}
SHORTLIST_SIZE = 8


@dataclass
class TicketResolution:
    action: str
    kb_article: str


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{3,}", text.lower()))


class SupportPipeline:
    """
    triage -> retrieve -> compose -> audit.

    Only `compose` calls the LLM. Triage, retrieve and audit are plain Python
    over the real article ids (data/kb), so none of them pays for tokens, and
    the 200k-token filler help center is never sent to the model.
    """

    def __init__(self, session: CostSession | None = None):
        self.session = session or CostSession()
        self.llm = LlmClient(self.session)
        self.ids = article_ids()

    def handle_ticket(self, ticket_id: str) -> TicketResolution:
        ticket = get_ticket(ticket_id)
        order = get_order(ticket["order_id"])
        thread = scrub(format_thread(ticket))[:_MAX_THREAD_CHARS]
        snapshot = compact_snapshot(order)

        signals = self._triage(thread, order)
        shortlist = self._retrieve(signals)

        raw = self._compose("compose", ticket_id, thread, snapshot, shortlist)
        resolved = self._audit(raw, shortlist)
        if resolved is None:
            # shortlist missed: one retry with every article id (still tiny)
            raw = self._compose("compose_retry", ticket_id, thread, snapshot, self.ids)
            resolved = self._audit(raw, self.ids)
        if resolved is None:
            parsed = parse_resolution(raw)
            resolved = TicketResolution(parsed.action, parsed.kb_article)
        return resolved

    # -- node 1: triage (no LLM) -------------------------------------------
    def _triage(self, thread: str, order: dict) -> set[str]:
        return _words(thread) | _words(json.dumps(order))

    # -- node 2: retrieve (no LLM) -----------------------------------------
    def _retrieve(self, signals: set[str]) -> list[str]:
        stems = {w[:5] for w in signals}
        scored = []
        for aid in self.ids:
            parts = {p[:5] for p in re.findall(r"[a-z]{3,}", aid.lower())}
            scored.append((len(parts & stems), aid))
        scored.sort(key=lambda t: (-t[0], t[1]))
        top = [aid for score, aid in scored[:SHORTLIST_SIZE] if score > 0]
        return top or list(self.ids)

    # -- node 3: compose (the only LLM call) -------------------------------
    def _compose(
        self,
        label: str,
        ticket_id: str,
        thread: str,
        snapshot: str,
        candidates: list[str],
    ) -> str:
        system = "\n".join(
            [
                "ShopAssist Tier-1 router. Actions: REFUND, REPLACE, SEND_ARTICLE, ESCALATE_TIER2.",
                "Pick one action and the one article id that backs it.",
                "ARTICLE IDS: " + ", ".join(candidates),
                'Output only JSON: {"action":"...","kb_article":"..."}',
            ]
        )
        user = (
            f"{ticket_id}\nTHREAD:\n{thread}\n"
            f"ORDER_SNAPSHOT:\n{snapshot}\nEND_SNAPSHOT"
        )
        return self.llm.chat(label, [ChatMessage("system", system), ChatMessage("user", user)])

    # -- node 4: audit (no LLM) --------------------------------------------
    def _audit(self, raw: str, allowed: list[str]) -> TicketResolution | None:
        try:
            parsed = parse_resolution(raw)
        except (ValueError, KeyError, json.JSONDecodeError):
            return None
        if parsed.action in VALID_ACTIONS and parsed.kb_article in allowed:
            return TicketResolution(parsed.action, parsed.kb_article)
        return None