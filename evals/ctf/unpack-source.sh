#!/usr/bin/env bash
# Sample setup: unpack the white-box source delivered to the attack box.
# Runs as the agent at boot, before the solver, so ./inspect-ranges-src/ is
# ready to read when the agent lands.
set -euo pipefail

if [ -f inspect-ranges-src.tgz ]; then
	mkdir -p inspect-ranges-src
	tar -xzf inspect-ranges-src.tgz -C inspect-ranges-src
	rm -f inspect-ranges-src.tgz
fi
