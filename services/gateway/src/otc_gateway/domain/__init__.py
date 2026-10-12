"""otc_gateway domain layer: the few rules the Gateway owns (it owns no aggregate).

Pure: the standard library only (import-linter `domain-purity`, the money guard's allow-list).
Time is an integer count of milliseconds handed in by the caller, so nothing here divides, rounds
or reads a clock.
"""
