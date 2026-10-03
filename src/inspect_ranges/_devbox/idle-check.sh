#!/usr/bin/env bash
# Stops the devbox once it has been idle for IDLE_MINUTES (from /etc/devbox.conf).
#
# Run every few minutes by devbox-idle.timer. "Stop" is an in-guest shutdown:
# the instance is launched with InstanceInitiatedShutdownBehavior=stop, so the
# EBS volume survives and the box never needs EC2 API permissions to stop itself.
set -euo pipefail

IDLE_MINUTES=60
# shellcheck source=/dev/null
[[ -f /etc/devbox.conf ]] && . /etc/devbox.conf

state=/var/lib/devbox
mkdir -p "$state"
now=$(date +%s)

activity=""
# SSH sessions, which includes VS Code Remote-SSH (tunnelled through SSM to sshd)
if ss -Htn state established '( sport = :22 )' | grep -q .; then
  activity="ssh"
# SSM shell sessions that don't go through sshd
elif pgrep -x ssm-session-worker >/dev/null; then
  activity="ssm"
# unattended work (evals, image builds) keeps the box up
elif awk -v l="$(cut -d' ' -f2 /proc/loadavg)" 'BEGIN { exit !(l >= 1.0) }'; then
  activity="load"
# explicit hold via `devbox-keepalive`
elif [[ -f "$state/keepalive-until" ]] && (($(cat "$state/keepalive-until") > now)); then
  activity="keepalive"
fi

if [[ -n "$activity" ]]; then
  echo "$now" >"$state/last-active"
  exit 0
fi

# idle time counts from the later of last activity and boot, so a box that was
# stopped while idle isn't stopped again the moment it starts
last_active=$(cat "$state/last-active" 2>/dev/null || echo 0)
uptime_secs=$(cut -d. -f1 /proc/uptime)
boot=$((now - uptime_secs))
((last_active < boot)) && last_active=$boot

idle_minutes=$(((now - last_active) / 60))
if ((idle_minutes >= IDLE_MINUTES)); then
  logger -t devbox-idle "idle for ${idle_minutes}m (limit ${IDLE_MINUTES}m); stopping"
  wall "devbox idle for ${idle_minutes} minutes; stopping now" || true
  shutdown -h now
fi
