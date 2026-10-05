"""otc_seed domain: the deterministic dataset, as pure Python (no framework, no I/O, no clock).

Everything here is a pure function of a string namespace or a literal: `deterministic_id`, the GS1
helpers, the master data and the six fabricated sagas. The persistence adapters live in
`otc_seed.infrastructure`; this package never imports them.
"""
