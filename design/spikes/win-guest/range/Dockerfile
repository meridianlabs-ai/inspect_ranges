# Range container for the Windows spike: libvirtd + QEMU + genisoimage (to
# build the autounattend ISO). VNC listens on container-local 127.0.0.1 only,
# solely to give the install a video device for virsh screenshot debugging.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    libvirt-daemon-system libvirt-clients virtinst \
    qemu-system-x86 qemu-utils \
    genisoimage \
    && rm -rf /var/lib/apt/lists/*

# same in-container qemu.conf as the earlier spikes (see l2-attach README)
RUN printf 'user = "root"\ngroup = "root"\nsecurity_driver = "none"\ndynamic_ownership = 0\nremember_owner = 0\ncgroup_controllers = []\n' \
    >> /etc/libvirt/qemu.conf

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
