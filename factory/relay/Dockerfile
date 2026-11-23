FROM alpine@sha256:f59abe656b692d901e184be3445e084786602108599d2a51d229c0f5a48c71bf
RUN apk add --no-cache pgbouncer aws-cli
COPY relay.sh /usr/local/bin/relay
USER 1000:1000
ENV HOME=/tmp
ENTRYPOINT ["relay"]
