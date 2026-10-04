# otel/opentelemetry-collector-contrib is a distroless image with no shell
# and no wget/curl, so Docker's exec-based HEALTHCHECK has nothing to run.
# We add a single statically-linked busybox binary (providing `wget`) purely
# for the healthcheck — the collector binary and its config are untouched.
FROM otel/opentelemetry-collector-contrib:0.159.0

COPY --from=busybox:1.36.1-musl /bin/busybox /bin/busybox
