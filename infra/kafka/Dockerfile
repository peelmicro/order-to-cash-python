# apache/kafka:4.3.1 provides the JVM and kafka-topics.sh (the broker image
# used by docker-compose.infra.yml — same tag, kept in lockstep). It has no
# YAML tooling, so a single pinned `yq` static binary is copied in from its
# own upstream image, exactly the way infra/otel-collector/Dockerfile adds a
# single busybox binary to a tool-less base image. Nothing about the Kafka
# distribution itself is modified.
FROM mikefarah/yq:4.47.2 AS yq

FROM apache/kafka:4.3.1
USER root
COPY --from=yq /usr/bin/yq /usr/local/bin/yq
COPY create-topics.sh /usr/local/bin/create-topics.sh
RUN chmod +x /usr/local/bin/yq /usr/local/bin/create-topics.sh
USER appuser

ENTRYPOINT ["/usr/local/bin/create-topics.sh"]
