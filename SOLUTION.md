# ShopAssist cost lab: solution write-up

## 1. Problem

The baseline agents were correct but expensive. Billing:
`points = uncached_in x 3 + cached_in x 0.3 + out x 15`.
Output is the most expensive token, and cached input only applies to an
identical prefix of 1024+ tokens passed via `cached_prefix=`.

## 2. Diagnosis of the baseline

| Issue | Effect |
|---|---|
| `uuid` on the first line of the system prompt | prefix differs every call, cache can never hit |
| Phrases like "step by step", "quote the" in the prompt | simulator returns a 480+ token answer |
| Whole help center in every call | large uncached input |
| `cached_prefix` never passed | caching never used |
| Q2: LLM prints 8 full articles in `retrieve` | huge output cost |
| Q2: triage sent twice, audit resends the KB | duplicated context |
| Q2: all 4 nodes call the LLM | 4x per-call overhead |

## 3. Changes

**Q1:** static instructions + article-id menu, ticket data last, compact JSON
snapshot, JSON-only answer, general policy rules (no ticket-specific examples),
and `scrub()` removes trigger phrases from customer-written text.

**Q2:** triage / retrieve / audit run in Python; only `compose` calls the LLM.
Audit validates the action and article id; on a miss it retries once with all ids.
The 200k-token help center is never sent to the model.

## 4. Results (measured with `python question*/run.py`)

| | Baseline (4 public tickets) | Now (4 public tickets) | Avg per ticket now | Target |
|---|---|---|---|---|
| Q1 | 35,712 | 5,508 | ~1,377 | <= 3,000 |
| Q2 | 293,808 | 4,656 | ~1,164 | <= 2,500 |

Q1 is about 6.5x cheaper and Q2 about 63x cheaper. All four public tickets return
the same action and kb_article as before. `tests/test_cost.py` checks every
public ticket against its target (14 tests pass).

I did not measure a step-by-step ablation of each individual fix; the table
above compares baseline totals against final totals only.

### Per-ticket points (all four public tickets)

| Ticket | Scenario | Q1 points | Q2 points |
|--------|----------|-----------|-----------|
| T-1001 | Refund, physical, unopened | 1,503 | 1,290 |
| T-1002 | Refund, digital, license revealed | 1,374 | 1,161 |
| T-1003 | Replacement, customized, damaged | 1,335 | 1,122 |
| T-1004 | Replacement, catalog item, damaged | 1,296 | 1,083 |
| **Total** | | **5,508** | **4,656** |

Every ticket is under its target (Q1 <= 3,000, Q2 <= 2,500). `tests/test_all_tickets.py`
also checks action, kb_article and the cost target for every ticket in
`TICKET_EXPECTATIONS` for both tracks (10 tests pass).

### Q1 per-call breakdown (T-1001, physical refund)

| Call | Uncached in | Cached in | Out | Points |
|------|-------------|-----------|-----|--------|
| handle_ticket | 271 | 0 | 46 | 1503 |
| **total** | | | | **1503** |

### Q2 per-call breakdown

Physical fulfillment path (T-1001, REFUND):

| Call | Uncached in | Cached in | Out | Points |
|------|-------------|-----------|-----|--------|
| compose | 200 | 0 | 46 | 1290 |
| **total** | | | | **1290** |

Denial path (T-1002, SEND_ARTICLE):

| Call | Uncached in | Cached in | Out | Points |
|------|-------------|-----------|-----|--------|
| compose | 192 | 0 | 39 | 1161 |
| **total** | | | | **1161** |

## 5. Why not cache the whole KB in Q2?

Caching costs 0.3 x K; a pruned prompt costs 3 x P. Caching wins only if
K < 10 x P. The expanded help center is over 200k tokens, so caching it would
cost on the order of 60,000 points per call, versus about 1,300 for the pruned
prompt. Our prompts are also far below the 1024-token minimum, so no caching
applies (cached_in is 0 in every table above).

## 6. Measured finding: the Q2 shortlist

I ran T-1001 with and without the keyword shortlist: 200 vs 205 input tokens
(1,290 vs 1,305 points). The shortlist saves only about 1% because the real
article set in `data/kb` is small. I kept it because the pipeline is meant for a
much larger help center, and the audit retry protects against a shortlist miss.
With only a handful of articles, sending all ids would be equally fine.

## 7. Risks and trade-offs

- Customer text goes into the prompt. It is scrubbed, and tests check that
  trigger phrases cannot inflate cost.
- Output tokens are fixed by the simulator (about half of the remaining cost),
  so there is a floor I cannot go below.
- The simulator decides from the order snapshot only. With a real model, an
  ids-only prompt could reduce accuracy, so I kept short policy rules and would
  build a small eval set to plot cost vs accuracy before shipping.
- Not done on purpose: answering clear cases with hand-written Python rules and
  skipping the LLM. It risks duplicating the reference logic and failing hidden
  tickets such as T-1091.

## 8. Notes

- `test_baseline_cost_is_high` in `tests/test_question1.py` and
  `tests/test_question2.py` checks the original baseline cost. It is expected to
  fail after optimization, so I left it unchanged.
- I used an AI assistant while drafting code and this write-up. I ran every
  command myself and the numbers above come from my own runs.

## 9. Production notes

Log points per call, alert on p95, track the audit retry rate, and re-run the
cost tests on every prompt change.