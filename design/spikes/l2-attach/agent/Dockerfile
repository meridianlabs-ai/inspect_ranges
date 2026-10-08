# Agent container: starts with no network (network_mode: none); the veth
# attach gives it `range0` on the lab segment.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    iproute2 iputils-ping iputils-arping tcpdump \
    openssh-client netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

CMD ["sleep", "infinity"]
