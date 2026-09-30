#!/usr/bin/env bash
# Provisions an inspect_ranges development host (Ubuntu 24.04, x86_64, KVM).
#
# Delivered as EC2 user-data by `devbox.py up`, which fills in the three
# placeholders below; cloud-init runs it once, as root, on first boot. It is
# idempotent and self-contained so it can later seed `inspect-ranges host
# install` and the eval-host AMI.
set -euo pipefail
exec > >(tee -a /var/log/devbox-bootstrap.log) 2>&1

DEVBOX_SSH_PUBKEY="__DEVBOX_SSH_PUBKEY__"
DEVBOX_IDLE_MINUTES="__DEVBOX_IDLE_MINUTES__"
DEVBOX_IDLE_CHECK_B64="__DEVBOX_IDLE_CHECK_B64__"

DEV_USER=ubuntu
DEV_HOME=/home/$DEV_USER
STATE=/var/lib/devbox
export DEBIAN_FRONTEND=noninteractive
APT="apt-get -y -o DPkg::Lock::Timeout=600"

mkdir -p "$STATE"
rm -f "$STATE/bootstrap-complete" "$STATE/kvm-missing"

# --- ssh access first, so `devbox.py up` can connect and wait on cloud-init --
install -d -m 700 -o $DEV_USER -g $DEV_USER "$DEV_HOME/.ssh"
touch "$DEV_HOME/.ssh/authorized_keys"
grep -qxF "$DEVBOX_SSH_PUBKEY" "$DEV_HOME/.ssh/authorized_keys" ||
  echo "$DEVBOX_SSH_PUBKEY" >>"$DEV_HOME/.ssh/authorized_keys"
chown $DEV_USER:$DEV_USER "$DEV_HOME/.ssh/authorized_keys"
chmod 600 "$DEV_HOME/.ssh/authorized_keys"

# --- apt repositories: Docker, HashiCorp (packer), GitHub CLI ---------------
$APT update
$APT install ca-certificates curl gnupg jq lsb-release
codename=$(. /etc/os-release && echo "$VERSION_CODENAME")
arch=$(dpkg --print-architecture)
install -m 0755 -d /etc/apt/keyrings

curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$arch signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $codename stable" \
  >/etc/apt/sources.list.d/docker.list

curl -fsSL https://apt.releases.hashicorp.com/gpg | gpg --batch --yes --dearmor -o /etc/apt/keyrings/hashicorp.gpg
echo "deb [arch=$arch signed-by=/etc/apt/keyrings/hashicorp.gpg] https://apt.releases.hashicorp.com $codename main" \
  >/etc/apt/sources.list.d/hashicorp.list

curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /etc/apt/keyrings/githubcli.gpg
chmod go+r /etc/apt/keyrings/githubcli.gpg
echo "deb [arch=$arch signed-by=/etc/apt/keyrings/githubcli.gpg] https://cli.github.com/packages stable main" \
  >/etc/apt/sources.list.d/github-cli.list

# --- packages ---------------------------------------------------------------
$APT update
$APT install \
  qemu-kvm libvirt-daemon-system libvirt-clients virtinst libguestfs-tools ovmf \
  xorriso cloud-image-utils bridge-utils iproute2 cpu-checker \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin \
  packer gh git tmux screen build-essential iperf3 fio unattended-upgrades

# oras (OCI artifacts for VM images): latest release, verified against its checksums
oras_version=$(curl -fsSL https://api.github.com/repos/oras-project/oras/releases/latest | jq -r .tag_name | sed 's/^v//')
oras_tmp=$(mktemp -d)
(
  cd "$oras_tmp"
  base="https://github.com/oras-project/oras/releases/download/v${oras_version}"
  curl -fsSLO "$base/oras_${oras_version}_linux_amd64.tar.gz"
  curl -fsSLO "$base/oras_${oras_version}_checksums.txt"
  grep " oras_${oras_version}_linux_amd64.tar.gz\$" "oras_${oras_version}_checksums.txt" | sha256sum -c -
  tar -xzf "oras_${oras_version}_linux_amd64.tar.gz" -C /usr/local/bin oras
)
rm -rf "$oras_tmp"

# --- virtualization ---------------------------------------------------------
usermod -aG kvm,libvirt,docker $DEV_USER
printf 'vhost_net\ntun\n' >/etc/modules-load.d/devbox.conf
modprobe vhost_net
modprobe tun
# nested virtualization is a launch-time CPU option; without it there is no /dev/kvm
[[ -e /dev/kvm ]] || touch "$STATE/kvm-missing"

# security updates without automatic reboots (a reboot would kill running ranges)
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

# --- idle auto-stop ---------------------------------------------------------
echo "IDLE_MINUTES=$DEVBOX_IDLE_MINUTES" >/etc/devbox.conf
echo "$DEVBOX_IDLE_CHECK_B64" | base64 -d >/usr/local/sbin/devbox-idle-check
chmod 755 /usr/local/sbin/devbox-idle-check

cat >/etc/systemd/system/devbox-idle.service <<'EOF'
[Unit]
Description=Stop the devbox when idle

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/devbox-idle-check
EOF

cat >/etc/systemd/system/devbox-idle.timer <<'EOF'
[Unit]
Description=Check devbox idleness every 5 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
EOF

cat >/usr/local/bin/devbox-keepalive <<'EOF'
#!/usr/bin/env bash
# Keep the devbox from auto-stopping: `devbox-keepalive 4h`, `devbox-keepalive 30m`, `devbox-keepalive off`
set -euo pipefail
f=/var/lib/devbox/keepalive-until
case "${1:-}" in
  off) sudo rm -f "$f"; echo "keepalive cleared" ;;
  *h) date -d "+${1%h} hours" +%s | sudo tee "$f" >/dev/null ;;
  *m) date -d "+${1%m} minutes" +%s | sudo tee "$f" >/dev/null ;;
  *) echo "usage: devbox-keepalive <N>h|<N>m|off" >&2; exit 2 ;;
esac
if [[ -f "$f" ]]; then echo "keeping alive until $(date -d "@$(cat "$f")")"; fi
EOF
chmod 755 /usr/local/bin/devbox-keepalive

systemctl daemon-reload
systemctl enable --now devbox-idle.timer

# --- developer user: uv and Claude Code (GitHub access is added later by `devbox.py github-token`)
sudo -u $DEV_USER -H bash <<'EOF'
set -euo pipefail
cd ~
command -v ~/.local/bin/uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
command -v ~/.local/bin/claude >/dev/null || curl -fsSL https://claude.ai/install.sh | bash
EOF

touch "$STATE/bootstrap-complete"
echo "devbox bootstrap complete"
