# Range container for the vsock spike: libvirtd + QEMU only — no bridges, no
# network tooling. The VM under test has zero NICs; control is pure vsock.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    libvirt-daemon-system libvirt-clients virtinst \
    qemu-system-x86 qemu-utils \
    cloud-image-utils \
    && rm -rf /var/lib/apt/lists/*

# same in-container qemu.conf as the l2-attach spike (see its README)
RUN printf 'user = "root"\ngroup = "root"\nsecurity_driver = "none"\ndynamic_ownership = 0\nremember_owner = 0\ncgroup_controllers = []\n' \
    >> /etc/libvirt/qemu.conf

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
