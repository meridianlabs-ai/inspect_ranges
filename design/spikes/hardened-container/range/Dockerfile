# Hardened range container: same stack as net-compile, but QEMU runs as the
# unprivileged libvirt-qemu user (created by the libvirt package) instead of
# root, with QEMU's own seccomp sandbox enabled. The outer jail (dropped
# capabilities, default seccomp/AppArmor, no-new-privileges) lives in
# compose.yaml; this image only has to work inside it.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    libvirt-daemon-system libvirt-clients virtinst \
    qemu-system-x86 qemu-utils \
    cloud-image-utils \
    iproute2 nftables \
    procps libcap2-bin \
    && rm -rf /var/lib/apt/lists/*

# vs the prototype qemu.conf (user root, no QEMU sandbox):
#  - QEMU drops to libvirt-qemu; dynamic_ownership lets libvirtd chown
#    overlays/seeds to it (CAP_CHOWN granted in compose.yaml)
#  - namespaces = [] : libvirt's private /dev mount namespace needs
#    CAP_SYS_ADMIN + mount, both denied by the default docker profiles
#  - seccomp_sandbox: QEMU's internal syscall filter, on
RUN printf 'user = "libvirt-qemu"\ngroup = "kvm"\nsecurity_driver = "none"\ndynamic_ownership = 1\nremember_owner = 0\ncgroup_controllers = []\nnamespaces = []\nseccomp_sandbox = 1\n' \
    >> /etc/libvirt/qemu.conf

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
