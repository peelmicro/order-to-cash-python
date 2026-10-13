# Premise check — brief_impl_observability_reliability.md (2026-10-12)
VERIFIED  paths exist: specs/observability_reliability/{requirements,design,tasks}.md, progress/spec_observability_reliability.md, progress/current.md — ls
VERIFIED  tasks.md "## How to read this file" (line 5) defines [ARM], [MEASURE], [LEADER], three mutation families, standing rules, Bounds (line 17)
VERIFIED  design.md §11 "The ported-idiom ledger" (423), §12 "Ported guards" (474), §14 "defect classes of #8's three rejections" (545)
VERIFIED  gate record "## Status" (line 3) carries 'Gate ruling (maintainer, 2026-10-12, verbatim): "approved"' G1-G4
VERIFIED  S4.15-S4.16 implement item 12 per G1 (tasks.md:34, 102-103): no envelope/topic stored, zero dead-letter records, OR12
VERIFIED  S8.7 (tasks.md:160) = feature_list.json id 27 -> in_review single-line edit; id 27 currently "in_progress"
VERIFIED  brief Bounds consistent with tasks.md Bounds: Status cells only (R16,R29,R56-R60,R62), uv add --package, infra/compose/.env*/n8n/apps/web forbidden in both; .arm/ not forbidden by tasks.md
VERIFIED  .arm git-ignored — git check-ignore -v .arm/r27/x -> .gitignore:87:/.arm/
VERIFIED  progress/current.md:31 "Process lessons from Phase 13, for every brief" (the four named lessons present)
VERIFIED  docker ps -> only otcpy-n8n running (unhealthy); all other otcpy containers Exited
FALSE-minor  brief's "S<n>.last" label: tasks.md has no ".last" ids; stage gates are S1.8, S2.7, S3.11, S4.23, S5.9, S6.8, S7.6 (placeholder, not a path)
