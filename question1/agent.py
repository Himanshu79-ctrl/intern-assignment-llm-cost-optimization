from __future__ import annotations

import json
import re
from dataclasses import dataclass

from shared.billing import CostSession
from shared.kb import article_ids
from shared.llm import ChatMessage, LlmClient
from shared.tools import format_thread, get_order, get_ticket

# Phrases that make the model (simulator) switch to a long, expensive answer.
# They must never appear anywhere in the prompt, including customer text.
_VERBOSE_HINTS = (
    "step by step",
    "full reasoning",
    "detailed plan",
    "double-check",
    "restate the ticket",
    "quote the",
)

_MAX_THREAD_CHARS = 1200


@dataclass
class TicketResolution:
    action: str
    kb_article: str
    customer_reply: str
    raw_completion: str


def parse_resolution(text: str) -> TicketResolution:
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError(f"No JSON in model output:\n{text[:400]}")
    data = json.loads(m.group())
    return TicketResolution(
        action=str(data["action"]).upper(),
        kb_article=str(data["kb_article"]),
        customer_reply=str(data.get("customer_reply", "")),
        raw_completion=text,
    )


def scrub(text: str) -> str:
    """Remove verbose-trigger phrases (e.g. from customer-written text)."""
    for hint in _VERBOSE_HINTS:
        text = re.sub(re.escape(hint), "", text, flags=re.IGNORECASE)
    return text


def compact_snapshot(order: dict) -> str:
    return json.dumps(order, separators=(",", ":"))


_RULES = (
    "Policy: returns of eligible physical items within the return window -> REFUND; "
    "digital items with a revealed license are not refundable -> SEND_ARTICLE; "
    "damaged customized items cannot be replaced -> ESCALATE_TIER2; "
    "damaged catalog items inside the damage window -> REPLACE. "
    "Cite the article id that states the rule you applied."
)


class SupportCopilot:
    """
    ShopAssist Tier-1 copilot (cost-optimised).

    One LLM call per ticket. Short static instructions + article id menu
    (not the full help center), ticket-specific data last, JSON-only answer.
    """

    def __init__(self, session: CostSession | None = None):
        self.session = session or CostSession()
        self.llm = LlmClient(self.session)

    def build_messages(self, ticket_id: str) -> list[ChatMessage]:
        ticket = get_ticket(ticket_id)
        order = get_order(ticket["order_id"])
        thread = scrub(format_thread(ticket))[:_MAX_THREAD_CHARS]

        system = "\n".join(
            [
                "ShopAssist Tier-1 router. Actions: REFUND, REPLACE, SEND_ARTICLE, ESCALATE_TIER2.",
                "Pick one action and the one article id that backs it.",
                _RULES,
                "ARTICLE IDS: " + ", ".join(article_ids()),
                'Output only JSON: {"action":"...","kb_article":"..."}',
            ]
        )
        user = (
            f"{ticket_id}\nTHREAD:\n{thread}\n"
            f"ORDER_SNAPSHOT:\n{compact_snapshot(order)}\nEND_SNAPSHOT"
        )
        return [ChatMessage("system", system), ChatMessage("user", user)]

    def handle_ticket(self, ticket_id: str) -> TicketResolution:
        messages = self.build_messages(ticket_id)
        completion = self.llm.chat("handle_ticket", messages)
        return parse_resolution(completion)