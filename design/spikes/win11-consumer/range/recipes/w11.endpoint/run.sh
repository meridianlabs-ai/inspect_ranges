#!/bin/sh
# The Windows 11 client endpoint: the declared low-privilege operator account,
# an on-demand SYSTEM maintenance task, and the endpoint marker. Runs as
# SYSTEM over the daemon (the IR_EXEC contract); exit 0 is demanded and never
# sufficient (verification is independent).
set -eu
"$IR_EXEC" --budget-ms 600000 --script "$PWD/endpoint.ps1"
echo "w11.endpoint: realized"
