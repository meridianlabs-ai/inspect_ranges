"""Run Inspect's sandbox conformance suite against the spike provider's agent VM.

Boots the range via the provider's own lifecycle, runs every `test_*` coroutine
in inspect_ai's self_check module against sandbox "default", tallies results,
and tears down. Usage: uv run python design/spikes/e2e-provider/run_self_check.py
"""

import asyncio
import inspect as pyinspect
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import inspect_ai.util._sandbox.self_check as self_check_module
from provider import RangesSpikeSandboxEnvironment


async def main() -> int:
    envs = await RangesSpikeSandboxEnvironment.sample_init("self_check", "range.yaml", {})
    env = envs["default"]
    passed: list[str] = []
    failed: list[tuple[str, str]] = []
    try:
        tests = [
            (name, fn)
            for name, fn in pyinspect.getmembers(self_check_module, pyinspect.iscoroutinefunction)
            if name.startswith("test_")
        ]
        for name, fn in sorted(tests):
            try:
                await fn(env)
                passed.append(name)
                print(f"  PASS {name}")
            except Exception as error:
                reason = "".join(traceback.format_exception_only(error)).strip()
                failed.append((name, reason[:160]))
                print(f"  FAIL {name}: {reason[:160]}")
    finally:
        await RangesSpikeSandboxEnvironment.sample_cleanup("self_check", None, envs, False)

    print(f"\nself_check: {len(passed)} passed, {len(failed)} failed of {len(passed) + len(failed)}")
    if failed:
        print("failures (the daemon punch list):")
        for name, reason in failed:
            print(f"  - {name}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
