# Range container for the lazy-pull spike: net-compile's recipe plus
# qemu-block-extra (Ubuntu packages the curl/http block driver separately).
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    libvirt-daemon-system libvirt-clients virtinst \
    qemu-system-x86 qemu-utils qemu-block-extra \
    cloud-image-utils \
    iproute2 nftables \
    && rm -rf /var/lib/apt/lists/*

RUN printf 'user = "root"\ngroup = "root"\nsecurity_driver = "none"\ndynamic_ownership = 0\nremember_owner = 0\ncgroup_controllers = []\n' \
    >> /etc/libvirt/qemu.conf

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
