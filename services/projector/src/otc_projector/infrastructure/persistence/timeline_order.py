"""The causal timeline order as an aggregation expression (`PR10`, `PR30`, `PR31`).

ONE function, `timeline_order_expression(entries_input)`, called by the live apply (input: the
stored array plus the new entry) and by the migration (input: the stored array): the two can
never order differently. The rule it evaluates is `domain/timeline_order.py`'s, and the
differential test checks the two against each other.

Each entry gets a depth in a fixpoint of `|entries|` `$reduce` rounds: the depth of its cause (the
FIRST entry of the same tie group, other than itself, whose `eventId` equals its `causationId`)
plus one, `0` when it has none (`$ifNull`: no `causationId` is not an error), capped at `|entries|`.
The cap never binds (every depth after round k is at most k, and there are `|entries|` rounds);
termination comes from the bounded `$reduce`, and a cycle's members climb in lockstep and tie on
depth. The array is then sorted by `occurredAt`, depth, `eventId`, and the depth is
discarded (`$unsetField`): it is computed and never stored.

`sortBy` is a dict whose key order IS the sort-key order, so it is written as a literal in that
order and the unit test asserts `list(sortBy) == ["occurredAt", "__depth", "eventId"]`. No
`$function`, no server-side JavaScript; `$sortArray` needs server 5.2+, `$unsetField` 5.0+
(`mongo:8.3.8`).
"""

DEPTH_FIELD = "__depth"


def timeline_order_expression(entries_input: object) -> dict[str, object]:
    cause = {
        "$arrayElemAt": [
            {
                "$filter": {
                    "input": "$$value",
                    "as": "p",
                    "cond": {
                        "$and": [
                            {"$eq": ["$$p.occurredAt", "$$e.occurredAt"]},
                            {"$ne": ["$$p.eventId", "$$e.eventId"]},
                            {"$eq": ["$$p.eventId", {"$ifNull": ["$$e.causationId", None]}]},
                        ]
                    },
                }
            },
            0,
        ]
    }
    relaxed = {
        "$map": {
            "input": "$$value",
            "as": "e",
            "in": {
                "$let": {
                    "vars": {"cause": cause},
                    "in": {
                        "$mergeObjects": [
                            "$$e",
                            {
                                DEPTH_FIELD: {
                                    "$min": [
                                        {"$size": "$$all"},
                                        {"$add": [{"$ifNull": [f"$$cause.{DEPTH_FIELD}", -1]}, 1]},
                                    ]
                                }
                            },
                        ]
                    },
                }
            },
        }
    }
    ranked = {
        "$reduce": {
            "input": "$$all",
            "initialValue": {
                "$map": {
                    "input": "$$all",
                    "as": "e",
                    "in": {"$mergeObjects": ["$$e", {DEPTH_FIELD: 0}]},
                }
            },
            "in": relaxed,
        }
    }
    return {
        "$let": {
            "vars": {"all": entries_input},
            "in": {
                "$let": {
                    "vars": {"ranked": ranked},
                    "in": {
                        "$map": {
                            "input": {
                                "$sortArray": {
                                    "input": "$$ranked",
                                    "sortBy": {"occurredAt": 1, DEPTH_FIELD: 1, "eventId": 1},
                                }
                            },
                            "as": "e",
                            "in": {"$unsetField": {"field": DEPTH_FIELD, "input": "$$e"}},
                        }
                    },
                }
            },
        }
    }
