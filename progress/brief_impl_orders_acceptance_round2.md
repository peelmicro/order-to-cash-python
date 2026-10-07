# Brief — implementer, feature 15 `orders_acceptance`, round 2 (last round without asking the maintainer)

**Task:** close every item of the section "What must change" in `progress/review_orders_acceptance.md` (items 1–7, D-1 … D-6 plus the quality run), exactly as written there, each with its named test and its arms. Read §5 (mutation table) and §6 (defects) of that review for the verbatim survivors. Feature 15 is `in_progress` (set by the reviewer).

- **D-1 is a production defect** (leaked `nats-responder` task and stop waiter, unclosed `AIOKafkaProducer` when Kafka is unreachable at boot): fix the code, then the test.
- For every fix, ask **"what fails if I revert this?"** and arm it (CLAUDE.md protocol: `cp` backup, mutation, the ONE named test, verbatim failure naming the claim, restore, `cmp`, clear caches, re-run green). #8's rounds 2 and 3 for this feature were lost to fixes that were themselves unguarded (`../order-to-cash-dotnet/progress/history.md` lines 786–787).
- Re-run the review's 36 killed mutations that touch files you change (they go stale when the path changes); list which.
- Bounds as in round 1 (`progress/brief_impl_orders_acceptance.md` "Files you may touch"). Do not edit CLAUDE.md (the lifespan wording, review Q1, is the leader's). The developer stack stays stopped.
- Append a "Round 2" section to `progress/impl_orders_acceptance.md` (per item: change, test, arms with verbatim failures; quality.sh exit / duration / count with per-file counts summing to the delta from 1867). Set feature 15 to `in_review` (that line only). No git writes. Return only "result in `progress/impl_orders_acceptance.md` (Round 2)" plus at most 5 lines.
