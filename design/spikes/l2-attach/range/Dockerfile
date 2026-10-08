# Range container: libvirtd + QEMU/KVM, per handoff §4. Boots VMs on bridges
# created inside this container's own network namespace.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    libvirt-daemon-system libvirt-clients virtinst \
    qemu-system-x86 qemu-utils \
    cloud-image-utils \
    iproute2 iputils-ping dnsmasq-base \
    && rm -rf /var/lib/apt/lists/*

# In-container libvirt: QEMU runs as root (container is the isolation boundary
# for this spike), no cgroup management (the container's cgroup already bounds
# us), no apparmor/selinux inside.
# dynamic_ownership/remember_owner off: the DAC driver sets trusted.* xattrs,
# which needs CAP_SYS_ADMIN we don't grant
RUN printf 'user = "root"\ngroup = "root"\nsecurity_driver = "none"\ndynamic_ownership = 0\nremember_owner = 0\ncgroup_controllers = []\n' \
    >> /etc/libvirt/qemu.conf

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
