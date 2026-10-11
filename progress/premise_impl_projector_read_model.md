# Premise check — brief_impl_projector_read_model.md

VERIFIED Gate ruling section is at end of spec file, G1 option (b), R1 ratified — grep -n "Gate ruling" -> line 159 of 165; text "G1 — APPROVED ... option (b)", "R1 — RATIFIED"
VERIFIED Task O2 = test-matrix R50-R55 (R54/R55 rows left TODO, ratification named); O3 = backlog 201 per G1, (b) branch edits services/seed/README.md:21, SA-6 text not this feature's; A3 = leader-owned .env.example Projector block; N2 = boot projector against dev stack — tasks.md lines 142,149,150,31
VERIFIED Uncommitted files — git status --short matches the brief's list (openapi.yaml, 2 generated headers, README, CLAUDE, AGENTS, history, current, plus .env.example, feature_list.json); sha prefix 8dd55c.. -> e73efb..
VERIFIED .env.example has PROJECTOR_KAFKA_CLIENT_ID=otc-projector, PROJECTOR_CONSUMER_GROUP=projector — .env.example:194-195
VERIFIED Feature 214 pending (unbounded nats.connect Orders/Fulfillment/Billing); feature 24 in_progress — python json load
VERIFIED tasks.md has "Files this feature may touch" (l.15) and "Must not touch" (l.23); feature 24's status line is allowed (l.21; O7); services/orders/src, services/fulfillment, services/billing are forbidden, so the three 214 composition.py files are forbidden; .env.example, progress/current.md forbidden. No brief statement contradicts them.
VERIFIED docker-compose.infra.yml exists; project name otcpy; otcpy-n8n container defined (l.423, under profile n8n)
VERIFIED progress/current.md:27 "Live dev data" paragraph mentions "16 duplicate fact records"
UNVERIFIABLE "leaving otcpy-n8n running" / `start` works — depends on live container state (not run)

Verdict: SAFE TO ACT (0 FALSE, 1 UNVERIFIABLE)
