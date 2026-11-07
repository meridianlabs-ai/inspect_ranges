"""tmux session mechanics for the `terminal` tool: command builders, send preparation, and the delta heuristic.

Adapted from terminal-bench's `TmuxSession` (`terminal_bench/terminal/tmux_session.py`, github.com/laude-institute/terminal-bench, Apache-2.0; see `design/inspect-ranges/LICENSES.md`): the `tmux wait -S` blocking completion signal, the previous-buffer delta heuristic with its two-label output, and the pane/history/pipe-pane session setup. Changes from the original: per-send wait channels scoped to named sessions (multiple sessions, and a channel never reused across sends or session lives), a shell-only guard input for blocking sends, and everything expressed as pure argv builders so the tool layer owns execution.

Everything here is pure: builders return argv lists, the heuristic maps strings to strings. The tool layer (`tool.py`) runs the argv through `sandbox().exec` and owns all state.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from functools import lru_cache

from .._brand import GUEST_BRAND

PANE_WIDTH = 160
PANE_HEIGHT = 40
HISTORY_LIMIT = 50_000
OUTPUT_CLIP_BYTES = 10_000

# session names key tmux targets, wait channels, and sink paths; the strict
# grammar makes them safe to splice into the pipe-pane shell line
SESSION_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}\Z")

# process names #{pane_current_command} reports that count as "at a shell":
# the blocking completion signal is shell text and must never be typed into
# whatever else owns the pane (a caught reverse shell, msfconsole, telnet)
SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh", "fish"})

_ENTER_KEYS = frozenset({"Enter", "C-m", "KPEnter", "C-j", "^M", "^J"})
_NEWLINE_CHARS = "\r\n"

SINK_DIR = f"/tmp/.{GUEST_BRAND}"


def sink_path(session: str) -> str:
    """The pipe-pane sink file for a session, under the capture directory."""
    return f"{SINK_DIR}/{session}.pipe"


def pane_sink_path(session: str, token: str, pane_id: str) -> str:
    """The pipe-pane sink file for one agent-created pane of a session life.

    `pane_id` is tmux's stable `%N` pane id. The name embeds the life `token` (`SessionState.token`): the hooks that write these sinks are re-set at every open with the current life's token, so a reopened name's new life can never append onto, or rediscover, a dead life's pane sinks.
    """
    return f"{SINK_DIR}/{session}-{token}-p{pane_id}.pipe"


def pane_sink_glob(session: str, token: str) -> str:
    """The shell glob matching one session life's per-pane sinks; the token keeps it exact, so another life's (or another session's) sinks never match."""
    return f"{SINK_DIR}/{session}-{token}-p%*.pipe"


_PANE_ID = re.compile(r"%\d+\Z")


def pane_id_from_sink(path: str, session: str, token: str) -> str | None:
    """The tmux pane id (`%N`) a per-pane sink path names, or `None` when the path is not one of this session life's pane sinks."""
    prefix = f"{SINK_DIR}/{session}-{token}-p"
    suffix = ".pipe"
    if not (path.startswith(prefix) and path.endswith(suffix)):
        return None
    pane_id = path[len(prefix) : -len(suffix)]
    return pane_id if _PANE_ID.match(pane_id) else None


def pane_label(pane_id: str) -> str:
    """The short pane label sibling cast and stream names carry (`%12` becomes `p12`); capture joins it to the session name with a dot, which the session grammar excludes, so a pane's names can never collide with another session's."""
    return f"p{pane_id.lstrip('%')}"


def wait_channel(session: str, nonce: str) -> str:
    """The per-send tmux wait channel the blocking completion signal uses.

    The channel carries a per-send `nonce` because tmux remembers a `wait -S` signal that fires with no waiter: a timed-out blocking send whose command later completes would otherwise leave a stale signal that releases the next blocking wait on the session immediately. Signals are server-wide and outlive sessions, and the send counter restarts at zero when a name is reopened, so the nonce the tool passes is the session life's `SessionState.token` plus the send counter, never the counter alone. The name is deliberately bland (`done-...`): it echoes in the pane, so it must not read as a harness marker (`_brand.py`).
    """
    return f"done-{session}-{nonce}"


def wait_channel_prefix(session: str, token: str) -> str:
    """The channel-name prefix shared by every send in one session life (the per-life `token` plus a send counter forms the nonce), used to anchor the echo scrub to our own channels."""
    return f"done-{session}-{token}-"


def valid_session_name(session: str) -> bool:
    """Whether a session name fits the grammar (lowercase, digits, `_`/`-`, max 32)."""
    return bool(SESSION_NAME.match(session))


def target(session: str) -> str:
    """The tmux target for a session: `=` pins exact-name matching (a bare name prefix-matches other sessions) and the trailing `:` selects the active pane, which pane-target commands require alongside `=`."""
    return f"={session}:"


def start_session_command(session: str) -> list[str]:
    """Argv creating the session: fixed pane size, deep history, pipe-pane into the sink.

    The sink truncates at open so a reopened session name never replays a previous life's output into its capture. `history-limit` applies only to windows created after it is set, so the global option is raised before `new-session` and restored after (the per-session set covers windows the agent creates later inside the session).
    """
    sink = sink_path(session)
    return [
        "bash",
        "-c",
        (
            f"mkdir -p {SINK_DIR} && : > {sink} && "
            f'prev="$(tmux show-options -gv history-limit 2>/dev/null)"; '
            f"tmux set-option -g history-limit {HISTORY_LIMIT} \\; "
            f"new-session -x {PANE_WIDTH} -y {PANE_HEIGHT} -d -s {session} \\; "
            f"set-option -t {target(session)} history-limit {HISTORY_LIMIT} \\; "
            f"pipe-pane -t {target(session)} 'cat >> {sink}' && "
            f'if [ -n "$prev" ]; then tmux set-option -g history-limit "$prev"; '
            f"else tmux set-option -gu history-limit; fi"
        ),
    ]


def has_session_command(session: str) -> list[str]:
    """Argv testing whether the session exists (exit 0 when it does; `=` pins exact-name matching, since a bare target prefix-matches other sessions)."""
    return ["tmux", "has-session", "-t", target(session)]


def kill_session_command(session: str) -> list[str]:
    """Argv killing the session (exact-name target)."""
    return ["tmux", "kill-session", "-t", target(session)]


PANE_HOOKS = ("after-new-window", "after-split-window")


def set_pane_hooks_commands(session: str, token: str) -> list[list[str]]:
    """Argvs installing the session-scoped tmux hooks that tap agent-created panes.

    `tmux new-window` or `split-window` typed inside the pane (the only way the agent gets more panes: send-keys bypasses client prefix handling) would otherwise leave capture on the original, now-idle pane. Each hook runs `pipe-pane` with no target, which tmux resolves to the hook's context pane, and that is the NEW pane (measured on tmux 3.4 for `new-window`, `split-window`, and the detached `new-window -d` alike; `#{hook_pane}` expands empty in these hooks there, so the context pane is the working handle). The sink name expands `#{pane_id}` at fire time and embeds the life `token`, so every pane of every life writes its own file.

    The hooks are session-scoped (`-t`, never `-g`): the guest's tmux server is shared with any sessions the agent creates wholesale for itself, which must stay untouched. They never fire for the session's primary pane, whose window exists before they are set. Each argv is a separate client command rather than a splice into the open's `bash -c`, and the hook argument (itself a tmux command string, parsed by tmux's config parser) stays inside this builder's fixed grammar, with no semicolons and the format reference inside the single-quoted shell command, so none of the client's separator or escape hazards apply.
    """
    sink = pane_sink_path(session, token, "#{pane_id}")
    hook_command = f"pipe-pane 'cat >> {sink}'"
    return [
        ["tmux", "set-hook", "-t", target(session), hook, hook_command]
        for hook in PANE_HOOKS
    ]


def remove_sink_command(session: str, token: str) -> list[str]:
    """Argv removing the session's pipe-pane sinks after close, the primary sink plus the life's per-pane sinks (token-exact glob): a closed session must not leave sink files behind (sessions still open at finalize keep theirs; the guest is torn down with the sample)."""
    return [
        "sh",
        "-c",
        f"rm -f {sink_path(session)} {pane_sink_glob(session, token)}",
    ]


def list_sessions_command() -> list[str]:
    """Argv listing session names, one per line."""
    return ["tmux", "list-sessions", "-F", "#{session_name}"]


def send_keys_command(session: str, keys: list[str]) -> list[str]:
    """Argv sending key arguments to the session's pane (exact-name target).

    `--` ends option parsing, so keystrokes starting with `-` are typed rather than read as `send-keys` flags.

    No argument may end in `;`. tmux's client reads a semicolon that terminates an argument as a command separator, `--` notwithstanding, and that is unrecoverable here: with nothing after it the character is silently dropped, and with another argument after it tmux rejects the whole command list, so nothing is typed at all. `send_keys_commands` splits those semicolons out into `semicolons_command` and is what callers should use; this raises rather than emit a command that would corrupt the agent's keystrokes.

    Raises:
        ValueError: A key argument ends in `;`.
    """
    offenders = [key for key in keys if key.endswith(";")]
    if offenders:
        raise ValueError(
            f"send_keys_command cannot type semicolon-terminated arguments "
            f"{offenders}: tmux would read the semicolon as a command "
            f"separator. Use send_keys_commands, which splits them out."
        )
    return ["tmux", "send-keys", "-t", target(session), "--", *keys]


def semicolons_command(session: str, count: int) -> list[str]:
    """Argv typing `count` semicolons as hex bytes (`3b`), the form tmux cannot mistake for a separator."""
    return ["tmux", "send-keys", "-t", target(session), "-H", *(["3b"] * count)]


def _split_trailing_semicolons(key: str) -> tuple[str, int]:
    """`key` without its trailing semicolons, and how many there were."""
    body = key.rstrip(";")
    return body, len(key) - len(body)


# tmux rejects a client command over ~16 KB ("command too long"), so larger
# key arguments split into literal chunks well under the limit (chars, so a
# fully multibyte chunk stays under 8 KB encoded)
SEND_CHUNK_CHARS = 2000


def _send_literal_commands(session: str, chunk: str) -> list[list[str]]:
    """The argv sequence typing one chunk verbatim: `-l` disables key-name lookup, so a chunk that happens to equal a key name (`Enter`) is typed, not pressed. Trailing semicolons split off into their hex form."""
    body, semicolons = _split_trailing_semicolons(chunk)
    commands: list[list[str]] = []
    if body:
        commands.append(["tmux", "send-keys", "-t", target(session), "-l", "--", body])
    if semicolons:
        commands.append(semicolons_command(session, semicolons))
    return commands


def _send_key_commands(session: str, key: str) -> list[list[str]]:
    """The argv sequence sending one short key argument.

    A key with no trailing semicolon keeps key-name lookup, so `C-c` as the entire keystrokes value is still pressed. A semicolon-terminated key goes literally, trailing semicolons split off into their hex form: the tool honors a key name only as the entire keystrokes value, and once the semicolons split off the body is not that, so lookup could only misfire. Left on, it would press a body spelling `up` or `home` (lookup is case-insensitive) rather than type it, the same silent corruption the line-break path guards against.
    """
    if not key.endswith(";"):
        return [send_keys_command(session, [key])]
    return _send_literal_commands(session, key)


def send_keys_commands(session: str, keys: list[str]) -> list[list[str]]:
    r"""The argv sequence sending the prepared key arguments, splitting oversized ones and semicolon-terminated ones.

    Short keys that carry no line break and no trailing semicolon go through `send_keys_command` in one command with key names honored. A longer key is never a tmux key name, so it splits into literal (`-l`) chunks that each fit tmux's client command limit; a 100 KB paste types through where a single `send-keys` would fail with "command too long".

    A key carrying a line break is typed literally too, whatever its length. It cannot be a key name, and leaving key-name lookup switched on for it would be actively harmful: lookup is case-insensitive, so a pasted line reading `up`, `end`, `space` or `tab` would be pressed as that key rather than typed. Pasting a wordlist or a one-column file would corrupt it silently, and the agent would read the damage as its own.

    A key ending in `;` cannot ride an ordinary argument at all, because tmux's client reads that semicolon as a command separator even after `--` (measured on tmux 3.4). Alone at the end of a command it costs one character silently: `send-keys -l -- 'x;'` types `x`. Followed by another argument it costs everything, because tmux rejects the command list before typing any of it: `send-keys -l -- 'echo x;' Enter` reports `unknown command: Enter`, and neither `echo x` nor the Enter reaches the pane.

    Fixed chunking manufactures the first case out of ordinary keystrokes: a 2000-character boundary landing just after a semicolon turns `int n=0;` into `int n=0` in the middle of a heredoc, and the pane reports it as the agent's own syntax error. So every trailing semicolon, at a chunk boundary or at the end of the agent's own keystrokes, goes as its hex byte. A `\;` is covered by the same split: tmux would otherwise eat the semicolon, then read the exposed trailing `\` as an escape and type a bare `;`.
    """
    chunked = any(len(key) > SEND_CHUNK_CHARS for key in keys)
    literal = any(_LINE_BREAK.search(key) for key in keys)
    if not chunked and not literal and not any(key.endswith(";") for key in keys):
        return [send_keys_command(session, keys)]
    commands: list[list[str]] = []
    for key in keys:
        if len(key) <= SEND_CHUNK_CHARS and not _LINE_BREAK.search(key):
            commands.extend(_send_key_commands(session, key))
        else:
            for i in range(0, len(key), SEND_CHUNK_CHARS):
                commands.extend(
                    _send_literal_commands(session, key[i : i + SEND_CHUNK_CHARS])
                )
    return commands


def capture_pane_command(session: str, entire: bool = False) -> list[str]:
    """Argv capturing the visible pane, or the whole scrollback with `entire` (exact-name target)."""
    extra = ["-S", "-"] if entire else []
    return ["tmux", "capture-pane", "-p", *extra, "-t", target(session)]


def pane_command_command(session: str) -> list[str]:
    """Argv reporting the pane's current foreground command name (exact-name target)."""
    return [
        "tmux",
        "display-message",
        "-p",
        "-t",
        target(session),
        "#{pane_current_command}",
    ]


def wait_done_command(session: str, timeout_s: float, nonce: str) -> list[str]:
    """Argv blocking on the send's wait channel under a hard timeout."""
    return ["timeout", f"{timeout_s}s", "tmux", "wait", wait_channel(session, nonce)]


def is_shell(pane_current_command: str) -> bool:
    """Whether the pane's foreground command is a shell (blocking sends allowed)."""
    return pane_current_command.strip() in SHELLS


def _is_enter_key(key: str) -> bool:
    return key in _ENTER_KEYS


def _executes(keystrokes: str) -> bool:
    """Whether the keystrokes end by executing a command (Enter key or trailing newline)."""
    return _is_enter_key(keystrokes) or bool(re.search(r"[\r\n]$", keystrokes))


_LINE_BREAK = re.compile(r"\r\n|\r|\n")


def carriage_returns(keystrokes: str) -> str:
    r"""`keystrokes` with every line break as CR, the byte a terminal sends when Enter is pressed.

    A line break typed as a literal byte reaches the pane as LF. Inside the pane's own pty that is indistinguishable from CR, because the line discipline translates CR to LF before any program sees it, which is why a local shell behaves identically either way. A program that puts the terminal in raw mode is handed the byte as sent: `ssh` does, and forwards it.

    That is the difference between a command running and nothing happening at all. A Windows console on the far side of an `ssh` session submits on CR and ignores a bare LF, so keystrokes ending in a literal newline sit unexecuted at the prompt and the next send types itself onto the same line.

    Keystrokes carrying no line break come back unchanged, so a key name as the whole value (`C-c`) is still looked up. An agent that needs a literal LF byte sends `C-j`, which is a key name and so passes through untouched.
    """
    return _LINE_BREAK.sub("\r", keystrokes)


def multiline_block(keystrokes: str) -> bool:
    """Whether a blocking send must be refused because the keystrokes span lines.

    An interior newline executes its line the moment it is typed, so by the time the appended completion signal reaches the pane an earlier line may have started a program (`telnet`, a caught shell, `msfconsole`) that would receive the signal text: the shell-only guard checked the pane before any of it was sent. Blocking sends take a single command line.
    """
    if not _executes(keystrokes) or _is_enter_key(keystrokes):
        return False
    return bool(re.search(r"[\r\n]", keystrokes.rstrip(_NEWLINE_CHARS)))


def _trim_trailing_semicolons(command: str) -> str:
    r"""Drop unescaped trailing semicolons (and surrounding whitespace) from a blocking command line: appending the `; tmux wait` signal after one would make `cmd;;`, a shell syntax error that never runs the command and stalls the send to its full timeout. A `\;` stays, since the shell reads it as a literal argument, not a separator."""
    trimmed = command.rstrip()
    while trimmed.endswith(";") and not trimmed.endswith("\\;"):
        trimmed = trimmed[:-1].rstrip()
    return trimmed


def _mask_line(line: str) -> tuple[str, str]:
    r"""Mask quoted and backslash-escaped characters of a command line with `x`, preserving length and positions, and report the pending parse state at end of line (`'` or `"` for an unclosed quote, `\` for a trailing escape, `""` when the line parses to completion). Shell operators and comment markers surface in the masked line only where the shell would honor them."""
    masked: list[str] = []
    quote = ""
    escaped = False
    for char in line:
        if escaped:
            escaped = False
            masked.append("x")
        elif quote == "'":
            if char == "'":
                quote = ""
            masked.append("x")
        elif quote == '"':
            if char == "\\":
                escaped = True
            elif char == '"':
                quote = ""
            masked.append("x")
        elif char == "\\":
            escaped = True
            masked.append("x")
        elif char in "'\"":
            quote = char
            masked.append("x")
        else:
            masked.append(char)
    return "".join(masked), "\\" if escaped else quote


# an unquoted `#` opens a comment only at the start of a word (after
# whitespace, an operator, or the start of the line); `foo#bar`, `$#`, and
# `${#var}` are not comments
_COMMENT_START = re.compile(r"(?:^|[\s;&|()])#")


def blocking_send_refusal(keystrokes: str) -> str | None:
    r"""The refusal message when a blocking command line cannot take the completion signal splice, or `None` when it can.

    The signal is appended to the line as `; tmux wait -S <channel>`, so the line must be a complete command the splice extends. An unclosed quote or a trailing `\` leaves the shell reading continuation input with the signal inside it; an unquoted `#` comment absorbs the splice, so the command runs but the signal never fires; a trailing unquoted `&` backgrounds the command (nothing to wait for) and, like a trailing `&&`/`||`/`|` continuation, splices into a shell syntax error that runs nothing. Each case would stall the send to its full timeout and report "it may still be running" falsely, so it is refused with the remedy named instead. Keystrokes that do not execute (or a bare Enter) are never inspected: they fall back to non-blocking or block on what was already typed, and non-blocking sends are otherwise byte-exact (`carriage_returns` normalizes the line break itself, nothing else).
    """
    if not _executes(keystrokes) or _is_enter_key(keystrokes):
        return None
    line = _trim_trailing_semicolons(keystrokes.rstrip(_NEWLINE_CHARS))
    masked, pending = _mask_line(line)
    if pending in ("'", '"'):
        name = "single" if pending == "'" else "double"
        return (
            f"Refusing block=True: the command line has an unclosed {name} quote, "
            "so the shell would wait for more input with the completion signal "
            "typed into the pending string. Close the quote, or use duration polling."
        )
    if pending == "\\":
        return (
            "Refusing block=True: the command line ends with a `\\` line "
            "continuation, so the appended completion signal would be read as part "
            "of the command instead of running after it. Drop the trailing "
            "backslash, or use duration polling."
        )
    if _COMMENT_START.search(masked):
        return (
            "Refusing block=True: the command line carries an unquoted `#` comment, "
            "which would absorb the appended completion signal: the command would "
            "run, but the send would stall to its full timeout. Remove the comment, "
            "or use duration polling."
        )
    tail = masked.rstrip()
    for op in ("&&", "||", "|"):
        if tail.endswith(op):
            return (
                f"Refusing block=True: the command line ends with `{op}`, an "
                "unfinished continuation, so the appended completion signal would "
                "splice into a shell syntax error and the command would never run. "
                "Complete the command, or use duration polling."
            )
    if tail.endswith("&"):
        return (
            "Refusing block=True: the command line ends with an unquoted `&`, "
            "which backgrounds the command, so the shell returns at once and there "
            "is no completion to wait for (and the appended completion signal "
            "would splice into a shell syntax error that runs nothing). Drop the "
            "`&`, or drop block=True and poll the background job with read."
        )
    return None


def prepare_send(
    session: str, keystrokes: str, block: bool, nonce: str
) -> tuple[list[str], bool]:
    """Prepare the send-keys arguments, appending the completion signal for a blocking send.

    Returns `(keys, is_blocking)`. A blocking send only makes sense when the keystrokes execute a command: the trailing Enter (key name or newline) is stripped, unescaped trailing semicolons are trimmed (they would make the signal splice a syntax error), and the per-send completion signal plus `Enter` are appended, so the whole line runs as `<command>; tmux wait -S <channel>`. Trimming the semicolons is what keeps the splice safe to send: the line ends in the channel name, so no argument ends in `;` for tmux to read as a command separator. Keystrokes that do not execute anything fall back to non-blocking even when `block` was requested; the caller refuses `multiline_block` keystrokes before calling.

    A non-blocking send carries its line breaks as CR rather than LF, for the reason in `carriage_returns`.
    """
    if not block or not _executes(keystrokes):
        return [carriage_returns(keystrokes)], False
    stripped = keystrokes
    if _is_enter_key(stripped):
        stripped = ""
    else:
        stripped = _trim_trailing_semicolons(stripped.rstrip(_NEWLINE_CHARS))
    signal = f"{stripped}; tmux wait -S {wait_channel(session, nonce)}"
    return [signal, "Enter"], True


def find_new_content(previous_buffer: str | None, current_buffer: str) -> str | None:
    """New content since `previous_buffer`, or `None` when it cannot be determined.

    The previous buffer (whitespace-stripped) is located inside the current one; everything from its final line onward is the delta. A rotated or cleared buffer loses the anchor and returns `None`, which the caller reports as the current screen rather than a wrong delta.
    """
    if previous_buffer is None:
        return None
    anchor = previous_buffer.strip()
    if anchor and anchor in current_buffer:
        idx = current_buffer.index(anchor)
        if "\n" in anchor:
            idx += anchor.rfind("\n")
        return current_buffer[idx:]
    return None


@lru_cache(maxsize=32)
def _wait_echo_patterns(
    channel_prefix: str | None,
) -> tuple[re.Pattern[str], re.Pattern[str], tuple[int, ...]]:
    r"""The unwrapped and wrapped-once forms of the blocking signal's pane echo, and each capture group's untrimmed space count.

    `capture-pane` inserts a newline where the pane wraps at `PANE_WIDTH`, and the wrap can fall between ANY two characters of the echoed suffix (or just before it); the suffix is far shorter than the pane width, so at most one wrap newline can land inside it. The wrapped pattern is the alternation of the suffix with a single newline at each possible split point, built once per channel prefix. With a `channel_prefix` (`wait_channel_prefix`) the channel part matches our prefix plus the send counter; without one it falls back to the generic `done-` form.

    A wrap that falls on one of the suffix's spaces also loses it, because `capture-pane` trims each line's trailing whitespace: `; tmux wait -S ...` comes back as `; tmux wait\n-S ...`, not `; tmux wait \n-S ...`. Every trailing space of a split's left side is therefore optional, which is what lets the two shapes the agent sees most (a wrap before `wait` and a wrap before `-S`) match at all.

    Each split whose left side ends in spaces captures the spaces that survived the trim, and the third element records, per capture group in pattern order, how many the untrimmed suffix carries there. `scrub_harness_echo` subtracts the survivors to learn how many columns the trim took out of the match at hand, so the wrap column it requires is exact for every split rather than a blanket allowance: only a wrap that lost spaces may sit short of `PANE_WIDTH`, and by exactly that many. A wrap at the very start of the suffix trims the command body instead, which is safe because `_trim_trailing_semicolons` has already stripped the body's trailing whitespace.
    """
    # the signal's channel digits end their logical line (Enter follows at
    # once), so a genuine wrap continuation carries nothing after them; the
    # lookahead keeps a next line that merely STARTS with digits out of the
    # broken form (the plain pattern stays unanchored: casts scrub the raw
    # stream, where the suffix is followed by the line's own control bytes)
    if channel_prefix is None:
        literal = "; tmux wait -S done-"
        tail, broken_tail = r"\S+", r"\S*\n\S+(?=\n|$)"
    else:
        literal = f"; tmux wait -S {channel_prefix}"
        tail, broken_tail = r"\d+", r"\d*\n\d+(?=\n|$)"
    plain = re.compile(re.escape(literal) + tail)
    alternatives: list[str] = []
    group_spaces: list[int] = []
    for split in range(len(literal)):
        left = literal[:split]
        kept = left.rstrip(" ")
        spaces = len(left) - len(kept)
        optional = ""
        if spaces:
            group_spaces.append(spaces)
            optional = "(" + " ?" * spaces + ")"
        alternatives.append(
            re.escape(kept) + optional + "\n" + re.escape(literal[split:]) + tail
        )
    alternatives.append(re.escape(literal) + broken_tail)
    return plain, re.compile("|".join(alternatives)), tuple(group_spaces)


def wait_echo_pattern(channel_prefix: str) -> re.Pattern[str]:
    """The unwrapped form of the blocking signal's pane echo, anchored to our own channel names (`wait_channel_prefix`).

    The raw pty stream (what pipe-pane records for the cast) carries no wrap newlines, so this plain form is the only one a cast scrub needs; `scrub_harness_echo` handles the wrapped forms `capture-pane` produces.
    """
    plain, _, _ = _wait_echo_patterns(channel_prefix)
    return plain


def scrub_harness_echo(text: str, channel_prefix: str | None = None) -> str:
    """Remove the blocking signal's pane echo from model-facing output.

    A blocking send appends `; tmux wait -S <channel>` to the command line, and the pane echoes it back; the model should read its own command, not the harness suffix. The pane wraps at `PANE_WIDTH`, so the echoed suffix can carry one capture newline anywhere inside it; a wrapped match is removed only when its interior newline sits at the wrap column, so agent-authored text that merely resembles the suffix mid-line survives. A wrap landing on a space ends the line short by the spaces `capture-pane` trimmed, so the required column for each match is `PANE_WIDTH` minus exactly the spaces that match lost; a wrap that could trim nothing (inside a word, or inside the channel digits) must sit at `PANE_WIDTH` itself, so a shorter line that merely ends in the suffix keeps the output after it. The column counts characters rather than display cells, so a command line carrying double-width characters wraps earlier than this can see and keeps its match; the prefix anchoring is what makes that merely a missed scrub rather than a wrong one. An echo line that ends at exactly the pane width with the channel digits, followed by an output line that is entirely digits, reads the same as a wrap inside the digits and is still over-scrubbed; the capture text alone cannot tell those apart (output with anything after its leading digits is already excluded, because a genuine continuation line ends with the channel digits). The tool threads `channel_prefix` (the session life's `wait_channel_prefix`), anchoring the match to our own channel names. Casts get the same treatment at assembly (`assemble_cast`, over the raw stream); the evidence mirror keeps the raw pane.
    """
    plain, wrapped, group_spaces = _wait_echo_patterns(channel_prefix)

    def scrub_wrapped(match: re.Match[str]) -> str:
        newline = match.string.index("\n", match.start(), match.end())
        column = newline - (match.string.rfind("\n", 0, newline) + 1)
        trimmed = 0
        for untrimmed, survived in zip(group_spaces, match.groups(), strict=True):
            if survived is not None:
                trimmed = untrimmed - len(survived)
                break
        return "" if column == PANE_WIDTH - trimmed else match.group(0)

    return plain.sub("", wrapped.sub(scrub_wrapped, text))


def label_output(
    new_content: str | None, visible_screen: str, first_read: bool = False
) -> str:
    """The model-facing read result: the raw delta when determinable; the screen, labeled, otherwise.

    The delta carries no header (viewer UX review, 2026-10-23). The fallback keeps its label because a re-rendered screen presented as new output would invite re-acting on old lines; a session's FIRST read is the exception (viewer UX review, 2026-10-24): no previously-seen screen exists, so there is nothing to re-act on and the label is noise.
    """
    if new_content is not None and new_content.strip():
        return new_content
    if first_read:
        return visible_screen
    return f"Current Terminal Screen:\n{visible_screen}"


def clip_output(text: str, limit: int = OUTPUT_CLIP_BYTES) -> str:
    """Clip to the last `limit` bytes, marking the cut; the full stream stays in the capture."""
    encoded = text.encode(errors="replace")
    if len(encoded) <= limit:
        return text
    clipped = encoded[-limit:].decode(errors="replace")
    return f"[output clipped to the last {limit} bytes; the full stream is in the session capture]\n{clipped}"


@dataclass
class SessionState:
    """Tool-side state for one open session."""

    previous_buffer: str | None = None
    chunks: list[tuple[float, bytes]] = field(default_factory=list[tuple[float, bytes]])
    markers: list[tuple[float, str]] = field(default_factory=list[tuple[float, str]])
    opened_wall: float = 0.0
    opened_monotonic: float = 0.0
    sends: int = 0
    token: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
