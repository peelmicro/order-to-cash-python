#!/usr/bin/env bash
# dev-stack.sh — run the whole #9 stack on this machine for the end-to-end suite: the infrastructure
# containers the services need, the migrations and the seed, the six services as `uv run` host processes
# and the web app (built, then served by apps/web/scripts/serve.mjs). One log file and one PID file per process.
#
#   scripts/dev-stack.sh up        # infra, migrate, seed, six services, web build + serve; returns once everything is ready
#   scripts/dev-stack.sh wait      # poll every readiness endpoint (exit 0 only when all answer)
#   scripts/dev-stack.sh status    # what runs, on which port, with which pid and log
#   scripts/dev-stack.sh down      # stop the processes this script started (by process group), then the infra it started
#   scripts/dev-stack.sh rebuild-web  # rebuild apps/web and restart only the web process (after an edit under apps/web/src)
#   scripts/dev-stack.sh env <cmd> # run <cmd> in the foreground with the stack's resolved ports exported
#
# Ports. Every host port the stack binds is read from the caller's environment first, then `.env`, then
# `.env.example`, and is exported resolved, so ONE override moves both the container's published port and every
# service's connection (the services read the same variable: POSTGRES_HOST_PORT for the DSN, MONGO_HOST_PORT, ...).
# On a machine whose 5432 is held by another project:
#
#   POSTGRES_HOST_PORT=5433 scripts/dev-stack.sh up
#
# A port that is taken stops `up` before anything starts, naming the port and its holder. Redpanda Console
# (REDPANDA_CONSOLE_HOST_PORT, 8080 by default) is NOT started: nothing the e2e suite or a service uses talks to it.
# KAFKA_HOST_PORT and NATS_CLIENT_HOST_PORT overrides also move KAFKA_BROKERS and NATS_URL unless those are set too.
#
# `down` leaves only what was up before `up`: infrastructure containers that were already running are not stopped,
# containers this script started are stopped (never removed, volumes are never touched), every process it started
# is killed by process group. Nothing else on the machine (another project's containers, for one) is touched.
#
# Do not start the `n8n` compose profile: it crash-loops without the rest of the n8n stack.

set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT/logs/dev-stack"
COMPOSE=(docker compose -p otcpy -f "$ROOT/docker-compose.infra.yml")
# Infrastructure the six services and the web app need. kafka-init creates the topics and exits 0.
INFRA=(postgres mongodb kafka nats kafka-init)
# name:port:module — Orders, Fulfillment, Billing, Notifications and the Projector speak uvicorn on 810x (README, "Running the services").
SERVICES=(orders:8101:otc_orders fulfillment:8102:otc_fulfillment billing:8103:otc_billing notifications:8104:otc_notifications projector:8105:otc_projector gateway::otc_gateway)

# The value of a variable: the caller's environment, then .env, then .env.example, then the default. Never `source`d:
# .env holds unquoted values with spaces (GATEWAY_OPERATOR_DISPLAY_NAME), which a shell would run as a command.
envval() {
  local name="$1" default="$2" value file
  if [ -n "${!name+x}" ]; then printf '%s' "${!name}"; return; fi
  for file in "$ROOT/.env" "$ROOT/.env.example"; do
    [ -f "$file" ] || continue
    value="$(grep -m1 "^${name}=" "$file" | cut -d= -f2-)"
    if [ -n "$value" ]; then printf '%s' "$value"; return; fi
  done
  printf '%s' "$default"
}

load_env() {
  local kafka_given="${KAFKA_HOST_PORT+x}" nats_given="${NATS_CLIENT_HOST_PORT+x}" brokers_given="${KAFKA_BROKERS+x}" url_given="${NATS_URL+x}"
  export POSTGRES_HOST_PORT="$(envval POSTGRES_HOST_PORT 5432)"
  export MONGO_HOST_PORT="$(envval MONGO_HOST_PORT 27017)"
  export KAFKA_HOST_PORT="$(envval KAFKA_HOST_PORT 9092)"
  export NATS_CLIENT_HOST_PORT="$(envval NATS_CLIENT_HOST_PORT 4222)"
  export NATS_MONITOR_HOST_PORT="$(envval NATS_MONITOR_HOST_PORT 8222)"
  export GATEWAY_PORT="$(envval GATEWAY_PORT 3001)"
  export WEB_PORT="$(envval WEB_PORT 3010)"
  # The OTel collector is not part of this stack, so nothing is exported unless the caller says where (empty = no export, as in the test suites). Without this
  # every service retries its OTLP export against a closed port and `down` takes minutes. `.env` is not consulted: its default points at a collector this script never starts.
  export OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT-}"
  [ -n "$kafka_given" ] && [ -z "$brokers_given" ] && export KAFKA_BROKERS="localhost:${KAFKA_HOST_PORT}"
  [ -n "$nats_given" ] && [ -z "$url_given" ] && export NATS_URL="nats://localhost:${NATS_CLIENT_HOST_PORT}"
  return 0
}

is_running() {
  local pidfile="$1"
  [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null
}

port_in_use() {
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

# Who holds a port: a container publishing it, else the process `ss` shows.
port_holder() {
  local port="$1" holder
  holder="$(docker ps --filter "publish=$port" --format '{{.Names}}' 2>/dev/null | paste -sd, -)"
  [ -n "$holder" ] && { printf 'container %s' "$holder"; return; }
  holder="$(ss -ltnpH "sport = :$port" 2>/dev/null | sed -n 's/.*users:(\(.*\)).*/\1/p' | head -1)"
  [ -n "$holder" ] && { printf 'process %s' "$holder"; return; }
  printf 'an unknown holder (not visible without privileges)'
}

container_running() {
  [ "$(docker inspect -f '{{.State.Running}}' "otcpy-$1" 2>/dev/null)" = "true" ]
}

# Fails fast, before anything starts, when a port this stack needs is held by something that is not already this stack.
check_ports() {
  local failed=0 entry name port var
  # service:VARIABLE — the variable that moves that service's published port, named in the hint below.
  for entry in postgres:POSTGRES_HOST_PORT mongodb:MONGO_HOST_PORT kafka:KAFKA_HOST_PORT nats:NATS_CLIENT_HOST_PORT nats:NATS_MONITOR_HOST_PORT; do
    name="${entry%%:*}"; var="${entry##*:}"; port="${!var}"
    container_running "$name" && continue
    if port_in_use "$port"; then
      echo "  [FAIL] port $port (needed by $name) is held by $(port_holder "$port") — free it, or set $var to a free port (e.g. $var=$((port + 1)))"
      failed=1
    fi
  done
  local spec rest svc_port
  for spec in "${SERVICES[@]}"; do
    name="${spec%%:*}"; rest="${spec#*:}"; svc_port="${rest%%:*}"
    [ -z "$svc_port" ] && svc_port="$GATEWAY_PORT"
    is_running "$RUN_DIR/$name.pid" && continue
    if port_in_use "$svc_port"; then
      echo "  [FAIL] port $svc_port (the $name service) is held by $(port_holder "$svc_port")"
      failed=1
    fi
  done
  if ! is_running "$RUN_DIR/web.pid" && port_in_use "$WEB_PORT"; then
    echo "  [FAIL] port $WEB_PORT (the web app) is held by $(port_holder "$WEB_PORT") — set WEB_PORT to a free port"
    failed=1
  fi
  return "$failed"
}

wait_http() {
  local url="$1" label="$2" seconds="$3" pidfile="${4:-}"
  local deadline=$((SECONDS + seconds))
  until curl -fsS -o /dev/null "$url" 2>/dev/null; do
    if [ -n "$pidfile" ] && ! is_running "$pidfile"; then
      echo "  [FAIL] $label exited before answering $url — see its log in $RUN_DIR"
      return 1
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
      echo "  [FAIL] $label did not answer $url within ${seconds}s — see its log in $RUN_DIR"
      return 1
    fi
    sleep 1
  done
  if [ -n "$pidfile" ] && ! is_running "$pidfile"; then
    echo "  [FAIL] $url answers, but $label is not running — another program holds that port"
    return 1
  fi
  echo "  [OK]   $label answers $url"
}

wait_healthy() {
  local name="$1" seconds="${2:-180}" deadline=$((SECONDS + ${2:-180}))
  until [ "$(docker inspect -f '{{.State.Health.Status}}' "otcpy-$name" 2>/dev/null)" = "healthy" ]; do
    if [ "$SECONDS" -ge "$deadline" ]; then echo "  [FAIL] otcpy-$name not healthy within ${seconds}s"; return 1; fi
    sleep 1
  done
  echo "  [OK]   otcpy-$name healthy"
}

start_process() {
  local name="$1"; shift
  local pidfile="$RUN_DIR/$name.pid" logfile="$RUN_DIR/$name.log"
  if is_running "$pidfile"; then
    echo "  [SKIP] $name already running (pid $(cat "$pidfile"))"
    return 0
  fi
  # setsid: each process leads its own group, so `down` signals the whole tree (uv run and node both spawn children).
  setsid "$@" >"$logfile" 2>&1 < /dev/null &
  echo $! >"$pidfile"
  echo "  [OK]   $name started (pid $!, log $logfile)"
}

group_alive() {
  kill -0 -- "-$1" 2>/dev/null || kill -0 "$1" 2>/dev/null
}

stop_process() {
  local name="$1" pidfile="$RUN_DIR/$1.pid" pid
  [ -f "$pidfile" ] || return 0
  pid="$(cat "$pidfile")"
  # The process GROUP is the unit: a child can outlive its leader (a leader that exits on TERM while its child is still draining), so "the leader is
  # gone" is not "the process is gone". `kill -0 -- -pid` succeeds while any member of the group lives.
  if group_alive "$pid"; then
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
    for _ in $(seq 1 "${STOP_WAIT_SECONDS:-30}"); do
      group_alive "$pid" || break
      sleep 1
    done
    if group_alive "$pid"; then
      kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null
    fi
    echo "  [OK]   $name stopped (pid $pid)"
  fi
  rm -f "$pidfile"
}

service_port() {
  local spec rest port
  for spec in "${SERVICES[@]}"; do
    [ "${spec%%:*}" = "$1" ] || continue
    rest="${spec#*:}"; port="${rest%%:*}"
    [ -z "$port" ] && port="$GATEWAY_PORT"
    printf '%s' "$port"; return
  done
}

cmd_up() {
  load_env
  mkdir -p "$RUN_DIR"
  echo "── ports"
  check_ports || return 1
  echo "  [OK]   every port this stack needs is free (or already this stack's)"

  echo "── infrastructure (${INFRA[*]})"
  # Remember which of them were NOT running, so `down` stops exactly those. Appended, never overwritten: a second `up` must not forget the first.
  local name
  for name in "${INFRA[@]}"; do
    [ "$name" = "kafka-init" ] && continue
    if ! container_running "$name" && ! grep -qx "$name" "$RUN_DIR/infra-started" 2>/dev/null; then
      echo "$name" >>"$RUN_DIR/infra-started"
    fi
  done
  "${COMPOSE[@]}" up -d --no-build "${INFRA[@]}" >"$RUN_DIR/infra.log" 2>&1 \
    || "${COMPOSE[@]}" up -d "${INFRA[@]}" >>"$RUN_DIR/infra.log" 2>&1 \
    || { echo "  [FAIL] docker compose — see $RUN_DIR/infra.log"; return 1; }
  for name in postgres mongodb kafka nats; do wait_healthy "$name" || return 1; done
  local deadline=$((SECONDS + 120))
  until [ "$(docker inspect -f '{{.State.Status}} {{.State.ExitCode}}' otcpy-kafka-init 2>/dev/null)" = "exited 0" ]; do
    [ "$SECONDS" -ge "$deadline" ] && { echo "  [FAIL] otcpy-kafka-init did not exit 0 within 120s"; return 1; }
    sleep 1
  done
  echo "  [OK]   otcpy-kafka-init created the topics and exited 0"

  echo "── migrations + seed (idempotent)"
  local svc
  for svc in orders fulfillment billing notifications; do
    (cd "$ROOT" && uv run --no-sync alembic -c "services/$svc/alembic.ini" upgrade head >"$RUN_DIR/migrate-$svc.log" 2>&1) \
      || { echo "  [FAIL] alembic $svc — see $RUN_DIR/migrate-$svc.log"; return 1; }
  done
  (cd "$ROOT" && uv run --no-sync python -m otc_seed >"$RUN_DIR/seed.log" 2>&1) \
    || { echo "  [FAIL] seed — see $RUN_DIR/seed.log"; return 1; }
  echo "  [OK]   four databases at head, seed applied"

  echo "── services"
  local spec rest port module
  for spec in "${SERVICES[@]}"; do
    name="${spec%%:*}"; rest="${spec#*:}"; port="${rest%%:*}"; module="${rest#*:}"
    if [ "$name" = "gateway" ]; then
      # `python -m otc_gateway` listens on GATEWAY_HOST:GATEWAY_PORT; plain `uvicorn --port` would ignore GATEWAY_PORT (#8 id 96).
      (cd "$ROOT" && start_process "$name" uv run --no-sync python -m otc_gateway)
    else
      (cd "$ROOT" && start_process "$name" uv run --no-sync uvicorn "$module.main:app" --port "$port")
    fi
  done
  for spec in "${SERVICES[@]}"; do
    name="${spec%%:*}"
    wait_http "http://localhost:$(service_port "$name")/health/ready" "$name" 180 "$RUN_DIR/$name.pid" || return 1
  done

  echo "── web (build, then serve)"
  if is_running "$RUN_DIR/web.pid"; then
    echo "  [SKIP] web already running (pid $(cat "$RUN_DIR/web.pid"))"
  else
    (cd "$ROOT/apps/web" && ./node_modules/.bin/vite build >"$RUN_DIR/web-build.log" 2>&1) \
      || { echo "  [FAIL] vite build — see $RUN_DIR/web-build.log"; return 1; }
    echo "  [OK]   web built"
    (cd "$ROOT/apps/web" && start_process web node --env-file-if-exists=../../.env scripts/serve.mjs preview)
  fi
  wait_http "http://localhost:${WEB_PORT}/login" "web" 120 "$RUN_DIR/web.pid" || return 1

  echo
  echo "Stack ready. Web: http://localhost:${WEB_PORT}  Gateway: http://localhost:${GATEWAY_PORT}"
  echo "Run the suite with: pnpm -C apps/web test:e2e    Stop with: scripts/dev-stack.sh down"
}

cmd_wait() {
  load_env
  local spec name failed=0
  for spec in "${SERVICES[@]}"; do
    name="${spec%%:*}"
    wait_http "http://localhost:$(service_port "$name")/health/ready" "$name" "${WAIT_SECONDS:-60}" || failed=1
  done
  wait_http "http://localhost:${WEB_PORT}/login" "web" "${WAIT_SECONDS:-60}" || failed=1
  return "$failed"
}

cmd_status() {
  load_env
  local spec name n
  for spec in "${SERVICES[@]}"; do
    name="${spec%%:*}"
    if is_running "$RUN_DIR/$name.pid"; then
      echo "  running  $name  port $(service_port "$name")  pid $(cat "$RUN_DIR/$name.pid")  log $RUN_DIR/$name.log"
    else
      echo "  stopped  $name"
    fi
  done
  if is_running "$RUN_DIR/web.pid"; then
    echo "  running  web  port $WEB_PORT  pid $(cat "$RUN_DIR/web.pid")  log $RUN_DIR/web.log"
  else
    echo "  stopped  web"
  fi
  for n in "${INFRA[@]}"; do
    if container_running "$n"; then echo "  running  otcpy-$n"; else echo "  stopped  otcpy-$n"; fi
  done
  [ -f "$RUN_DIR/infra-started" ] && echo "  infra started by this script (down stops these): $(paste -sd' ' "$RUN_DIR/infra-started")"
  return 0
}

cmd_down() {
  load_env
  stop_process web
  local i spec
  for ((i = ${#SERVICES[@]} - 1; i >= 0; i--)); do
    spec="${SERVICES[$i]}"
    stop_process "${spec%%:*}"
  done
  # Only the containers THIS script started. A container that was already running before `up` is not ours to stop.
  if [ -f "$RUN_DIR/infra-started" ]; then
    local mine
    mine="$(paste -sd' ' "$RUN_DIR/infra-started")"
    # shellcheck disable=SC2086
    "${COMPOSE[@]}" stop $mine >"$RUN_DIR/infra-down.log" 2>&1 || echo "  [WARN] docker compose stop — see $RUN_DIR/infra-down.log"
    echo "  [OK]   stopped containers this script started: $mine"
    rm -f "$RUN_DIR/infra-started"
  fi
  # Anything of ours still holding a port is a leak, whatever the pid files say.
  local held="" port
  for spec in "${SERVICES[@]}"; do
    port="$(service_port "${spec%%:*}")"
    port_in_use "$port" && held="$held $port"
  done
  port_in_use "$WEB_PORT" && held="$held $WEB_PORT"
  if [ -n "$held" ]; then
    echo "  [WARN] ports this stack binds are still held:$held"
    return 1
  fi
  echo "  [OK]   no process of this stack is left, none of its ports is held"
}

cmd_rebuild_web() {
  load_env
  mkdir -p "$RUN_DIR"
  stop_process web
  (cd "$ROOT/apps/web" && ./node_modules/.bin/vite build >"$RUN_DIR/web-build.log" 2>&1) \
    || { echo "  [FAIL] vite build — see $RUN_DIR/web-build.log"; return 1; }
  echo "  [OK]   web rebuilt"
  (cd "$ROOT/apps/web" && start_process web node --env-file-if-exists=../../.env scripts/serve.mjs preview)
  wait_http "http://localhost:${WEB_PORT}/login" "web" 120 "$RUN_DIR/web.pid"
}

case "${1:-}" in
  up) cmd_up ;;
  rebuild-web) cmd_rebuild_web ;;
  wait) cmd_wait ;;
  status) cmd_status ;;
  down) cmd_down ;;
  env)
    shift
    [ "$#" -gt 0 ] || { echo "usage: $0 env <command> [args...]"; exit 2; }
    load_env
    cd "$ROOT" && exec "$@"
    ;;
  *) echo "usage: $0 {up|wait|status|down|rebuild-web|env <command> [args...]}"; exit 2 ;;
esac
