#!/usr/bin/env bash
# create-topics.sh — the single source of truth for Kafka topology creation.
#
# THIS SCRIPT NEVER HARDCODES A TOPIC NAME. It parses the channel addresses
# out of the AsyncAPI spec (specs/shared/asyncapi.yaml, mounted read-only)
# and creates exactly those. If the spec cannot be read or parsed, or if the
# broker's final topic list disagrees with the spec, this script FAILS LOUDLY
# (non-zero exit) rather than silently creating the wrong topology.
#
# Run identically by:
#   - the `kafka-init` one-shot service in docker-compose.infra.yml, and
#   - the `pnpm kafka:topics` script (via `docker compose run --rm kafka-init`)
# — one script, two callers, zero duplicated logic.
set -euo pipefail

SPEC_PATH="${ASYNCAPI_SPEC_PATH:-/specs/asyncapi.yaml}"
BOOTSTRAP_SERVER="${KAFKA_BOOTSTRAP_SERVER:-kafka:29092}"
# Single-node dev broker, so replication factor is fixed at 1 — there is only
# one broker to replicate to. Partition count is set higher than 1 (6, one of
# which is "spare" beyond today's known consumer groups: orders.saga,
# projector, notifications) purely to allow future consumer-group
# parallelism. This is safe for the ordering guarantee the saga depends on:
# every producer keys these topics by `correlationId` (the order id).
# Kafka's default partitioner hashes the key, so all facts about one order
# always land on the *same* partition and are read in emission order by any
# consumer of that partition — regardless of how many partitions the topic
# has.
PARTITIONS="${KAFKA_TOPIC_PARTITIONS:-6}"
REPLICATION_FACTOR="${KAFKA_TOPIC_REPLICATION_FACTOR:-1}"
KAFKA_TOPICS_BIN="${KAFKA_TOPICS_BIN:-/opt/kafka/bin/kafka-topics.sh}"
YQ_BIN="${YQ_BIN:-yq}"

echo "== otc kafka topology =="
echo "spec:               $SPEC_PATH"
echo "bootstrap server:    $BOOTSTRAP_SERVER"
echo "partitions:          $PARTITIONS"
echo "replication factor:  $REPLICATION_FACTOR"
echo

if [ ! -f "$SPEC_PATH" ]; then
  echo "FATAL: asyncapi spec not found at $SPEC_PATH — refusing to fall back to a hardcoded topic list." >&2
  exit 1
fi

# Derive the Kafka topic list directly from the spec's own channel bindings.
# A channel is a Kafka topic iff it declares `bindings.kafka.topic` — this is
# the spec's own structural signal for "this channel lives on the fact
# stream", not a guess based on matching channel names or addresses. Every
# NATS RPC channel in this spec has no `bindings.kafka` block at all, so it
# is correctly excluded: NATS core has no topology to create.
if ! TOPICS="$("$YQ_BIN" eval '.channels[] | select(.bindings.kafka.topic != null) | .bindings.kafka.topic' "$SPEC_PATH" 2>&1)"; then
  echo "FATAL: could not parse $SPEC_PATH with yq:" >&2
  echo "$TOPICS" >&2
  exit 1
fi

# Strip blank lines defensively (a spec with zero kafka-bound channels would
# otherwise pass silently with an empty topic set — that must fail loudly).
TOPICS="$(printf '%s\n' "$TOPICS" | sed '/^\s*$/d')"

if [ -z "$TOPICS" ]; then
  echo "FATAL: parsed $SPEC_PATH successfully but found zero channels with a bindings.kafka.topic — refusing to proceed with an empty topology." >&2
  exit 1
fi

TOPIC_COUNT="$(printf '%s\n' "$TOPICS" | wc -l | tr -d ' ')"
echo "Derived $TOPIC_COUNT Kafka topic(s) from the spec:"
printf '  - %s\n' $TOPICS
echo

# ── create idempotently ─────────────────────────────────────────────────
while IFS= read -r topic; do
  [ -z "$topic" ] && continue
  echo "Ensuring topic exists: $topic"
  "$KAFKA_TOPICS_BIN" --bootstrap-server "$BOOTSTRAP_SERVER" \
    --create --if-not-exists \
    --topic "$topic" \
    --partitions "$PARTITIONS" \
    --replication-factor "$REPLICATION_FACTOR"
done <<< "$TOPICS"
echo

# ── verify: assert the final topology matches the spec EXACTLY ─────────
# Not just "are the spec's topics present" (a superset check would silently
# tolerate drift/leftovers) but "is the broker's non-internal topic set
# exactly the spec's topic set" — any topic in the spec that failed to
# create, or any non-spec topic on the broker, is a hard failure.
#
# Both sides of this comparison are derived from the same source with no
# assumed application prefix: EXPECTED is $TOPICS itself (the spec is the
# only source of truth — no re-deriving a prefix from it); ACTUAL is
# excluded only for Kafka's own internal topics, which by Kafka convention
# (not a guess of ours) always begin with "__" (e.g. __consumer_offsets).
# Filtering by a literal application namespace (e.g. "otc.") would silently
# pass verification even if a spec-declared topic under a different prefix
# never got created — see progress/review_messaging_topology.md D3.
ACTUAL="$("$KAFKA_TOPICS_BIN" --bootstrap-server "$BOOTSTRAP_SERVER" --list | grep -v '^__' | sort || true)"
EXPECTED="$(printf '%s\n' "$TOPICS" | sort)"

if [ "$ACTUAL" != "$EXPECTED" ]; then
  echo "FATAL: the broker's topic set does not match the spec exactly." >&2
  echo "--- expected (from spec) ---" >&2
  echo "$EXPECTED" >&2
  echo "--- actual (on broker, excluding Kafka's own __internal topics) ---" >&2
  echo "$ACTUAL" >&2
  exit 1
fi

# ── verify shape: partition count and replication factor, per topic ────
# `--create --if-not-exists` is a silent no-op against a topic that already
# exists with a DIFFERENT shape — the name-set check above cannot see that.
# We do not auto-alter a drifted topic here: changing partition count on an
# existing topic changes key→partition routing and would silently reorder
# a saga's in-flight per-order facts, and a replication-factor change needs
# a planned reassignment. Drift is therefore a hard failure that names the
# affected topic(s) and says a human must intervene — see
# progress/review_messaging_topology.md D4.
DRIFTED=""
while IFS= read -r topic; do
  [ -z "$topic" ] && continue
  DESCRIBE_LINE="$("$KAFKA_TOPICS_BIN" --bootstrap-server "$BOOTSTRAP_SERVER" --describe --topic "$topic" | head -n1)"
  ACTUAL_PARTITIONS="$(printf '%s\n' "$DESCRIBE_LINE" | sed -n 's/.*PartitionCount: *\([0-9][0-9]*\).*/\1/p')"
  ACTUAL_RF="$(printf '%s\n' "$DESCRIBE_LINE" | sed -n 's/.*ReplicationFactor: *\([0-9][0-9]*\).*/\1/p')"
  if [ "$ACTUAL_PARTITIONS" != "$PARTITIONS" ] || [ "$ACTUAL_RF" != "$REPLICATION_FACTOR" ]; then
    echo "DRIFT: $topic has partitions=${ACTUAL_PARTITIONS:-?} replication=${ACTUAL_RF:-?}, expected partitions=$PARTITIONS replication=$REPLICATION_FACTOR" >&2
    DRIFTED="$DRIFTED $topic"
  fi
done <<< "$TOPICS"

if [ -n "$DRIFTED" ]; then
  echo "FATAL: the following topic(s) exist with the wrong shape (partition count and/or replication factor):$DRIFTED" >&2
  echo "This script never auto-alters an existing topic's shape — repartitioning changes key->partition routing (would silently reorder a saga's in-flight per-order facts) and replication-factor changes need a planned reassignment. Fix manually: on a dev stack, delete and let this script recreate the topic (kafka-topics.sh --delete --topic <name>, then re-run); in a real environment, plan a kafka-reassign-partitions run instead." >&2
  exit 1
fi

echo "OK: all $TOPIC_COUNT spec-derived Kafka topic(s) verified present on the broker with the correct name, partition count ($PARTITIONS) and replication factor ($REPLICATION_FACTOR), and no others."
