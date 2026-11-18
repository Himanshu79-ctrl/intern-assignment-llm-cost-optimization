from __future__ import annotations

import pytest

from eval.reference import TICKET_EXPECTATIONS
from question1.agent import SupportCopilot
from question2.agent import SupportPipeline

TICKETS = sorted(TICKET_EXPECTATIONS)
Q1_TARGET = 3000
Q2_TARGET = 2500


@pytest.mark.parametrize("tid", TICKETS)
def test_q1_matches_expected_and_budget(tid):
    copilot = SupportCopilot()
    got = copilot.handle_ticket(tid)
    exp = TICKET_EXPECTATIONS[tid]
    assert got.action == exp.action
    assert got.kb_article == exp.kb_article
    assert copilot.session.total_points() <= Q1_TARGET


@pytest.mark.parametrize("tid", TICKETS)
def test_q2_matches_expected_and_budget(tid):
    pipe = SupportPipeline()
    got = pipe.handle_ticket(tid)
    exp = TICKET_EXPECTATIONS[tid]
    assert got.action == exp.action
    assert got.kb_article == exp.kb_article
    assert pipe.session.total_points() <= Q2_TARGET
