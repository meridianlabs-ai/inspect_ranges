"""Unit tests for the terminal tool's session mechanics and cast assembly (pure layer)."""

import json

import pytest
from inspect_ranges._terminal.cast import assemble_cast
from inspect_ranges._terminal.session import (
    OUTPUT_CLIP_BYTES,
    PANE_WIDTH,
    SEND_CHUNK_CHARS,
    SessionState,
    blocking_send_refusal,
    capture_pane_command,
    clip_output,
    find_new_content,
    is_shell,
    label_output,
    multiline_block,
    pane_id_from_sink,
    pane_label,
    pane_sink_glob,
    pane_sink_path,
    prepare_send,
    remove_sink_command,
    scrub_harness_echo,
    send_keys_command,
    send_keys_commands,
    set_pane_hooks_commands,
    start_session_command,
    valid_session_name,
    wait_channel,
    wait_channel_prefix,
    wait_done_command,
)


@pytest.mark.parametrize(
    ("name", "valid"),
    [
        ("main", True),
        ("listener-1", True),
        ("msf_console", True),
        ("a" * 32, True),
        ("", False),
        ("-lead", False),
        ("UPPER", False),
        ("has space", False),
        ("a" * 33, False),
        ("semi;colon", False),
        ("dot.name", False),
    ],
)
def test_session_name_grammar(name: str, valid: bool) -> None:
    assert valid_session_name(name) is valid


@pytest.mark.parametrize(
    ("keystrokes", "block", "expected_keys", "expected_blocking"),
    [
        # a non-blocking line break goes as CR, not LF: a raw-mode pty is
        # handed the byte as sent, and a Windows console across an ssh
        # session submits on CR and ignores a bare LF
        ("ls -la\n", False, ["ls -la\r"], False),
        ("ls -la\r\n", False, ["ls -la\r"], False),
        ("ls -la\r", False, ["ls -la\r"], False),
        ("\n", False, ["\r"], False),
        ("\r\r", False, ["\r\r"], False),
        ("one\ntwo\n", False, ["one\rtwo\r"], False),
        ("a\n\nb", False, ["a\r\rb"], False),
        # without a newline nothing changes: key names are still looked up and
        # a bare fragment is still typed verbatim
        ("C-c", False, ["C-c"], False),
        ("", False, [""], False),
        ("partial", False, ["partial"], False),
        # blocking strips the trailing newline and appends the signal; the
        # trimming is what keeps it sendable, since the line then ends in the
        # channel name rather than a `;` tmux would read as a separator
        ("ls -la\n", True, ["ls -la; tmux wait -S done-s-ab-7", "Enter"], True),
        ("make\r\n", True, ["make; tmux wait -S done-s-ab-7", "Enter"], True),
        # a bare Enter key blocks on whatever was already typed
        ("Enter", True, ["; tmux wait -S done-s-ab-7", "Enter"], True),
        # unescaped trailing semicolons are trimmed: `cmd;; tmux wait` is a
        # shell syntax error that runs nothing and stalls to the timeout
        ("echo hi;\n", True, ["echo hi; tmux wait -S done-s-ab-7", "Enter"], True),
        ("ls ; ;\n", True, ["ls; tmux wait -S done-s-ab-7", "Enter"], True),
        # an escaped `\;` is a literal shell argument, not a separator: it stays
        (
            "echo a\\;\n",
            True,
            ["echo a\\;; tmux wait -S done-s-ab-7", "Enter"],
            True,
        ),
        # keystrokes that execute nothing fall back to non-blocking
        ("ls -la", True, ["ls -la"], False),
        ("C-c", True, ["C-c"], False),
    ],
)
def test_prepare_send(
    keystrokes: str, block: bool, expected_keys: list[str], expected_blocking: bool
) -> None:
    keys, blocking = prepare_send("s", keystrokes, block, "ab-7")
    assert keys == expected_keys
    assert blocking is expected_blocking


@pytest.mark.parametrize(
    ("keystrokes", "fragment"),
    [
        # complete single commands take the splice: no refusal
        ("ls -la\n", None),
        ("echo hi;\n", None),  # trailing `;` is trimmed by prepare_send
        ("echo a\\;\n", None),  # escaped `\;` is a literal argument, kept
        ("echo 'quoted & | # ok'\n", None),  # operators inside quotes are inert
        ('grep "#" file\n', None),
        ("echo a\\& b\\#c\n", None),  # escaped operator and hash are inert
        ("echo foo#bar\n", None),  # `#` mid-word is not a comment
        ("echo $#\n", None),  # a parameter, not a comment
        ("Enter", None),  # bare Enter blocks on what was already typed
        ("C-c", None),  # does not execute: falls back to non-blocking
        ("nc -lvnp 4444 &", None),  # no trailing newline: non-blocking anyway
        # backgrounding contradicts block, and `&;` is a syntax error
        ("nc -lvnp 4444 &\n", "`&`"),
        ("sleep 5 & \n", "`&`"),
        # unfinished continuations splice into a syntax error that runs nothing
        ("echo pre &&\n", "`&&`"),
        ("echo pre ||\n", "`||`"),
        ("cat file |\n", "`|`"),
        # an unquoted comment absorbs the splice: the command runs, the signal never fires
        ("echo hi  # check output\n", "comment"),
        ("# just a note\n", "comment"),
        ("echo done; # trailing\n", "comment"),
        # an unclosed quote wedges the shell reading continuation input
        ("echo 'unclosed\n", "single quote"),
        ('echo "unclosed\n', "double quote"),
        # a trailing escape absorbs the splice into the command's arguments
        ("echo foo \\\n", "backslash"),
    ],
)
def test_blocking_send_refusal(keystrokes: str, fragment: str | None) -> None:
    """A blocking line the completion-signal splice would break is refused with the problem and remedy named; complete lines and non-blocking fallbacks pass (pre-ship P1-6)."""
    refusal = blocking_send_refusal(keystrokes)
    if fragment is None:
        assert refusal is None
    else:
        assert refusal is not None
        assert refusal.startswith("Refusing block=True")
        assert fragment in refusal


def test_wait_channel_is_per_send() -> None:
    """A timed-out send's late signal must never release a later send's wait: tmux remembers unconsumed signals, so each send gets its own channel."""
    assert wait_channel("s", "ab-0") != wait_channel("s", "ab-1")
    assert (
        prepare_send("s", "ls\n", True, "ab-0")[0]
        != prepare_send("s", "ls\n", True, "ab-1")[0]
    )


def test_wait_token_is_per_life() -> None:
    """Tmux signals are server-wide and outlive sessions, and the send counter restarts at zero on reopen, so each session life must carry a fresh channel token."""
    assert SessionState().token != SessionState().token


@pytest.mark.parametrize(
    ("keystrokes", "refused"),
    [
        # an interior newline runs its line immediately: the signal could land
        # inside a program that line started, so block refuses it
        ("cat\nhello\n", True),
        ("nc host 4444\r\nls\n", True),
        # single command lines, bare Enter, and non-executing keystrokes pass
        ("ls -la\n", False),
        ("make\r\n", False),
        ("Enter", False),
        ("C-c", False),
        ("a\nb", False),  # no trailing newline: falls back to non-blocking anyway
    ],
)
def test_multiline_block(keystrokes: str, refused: bool) -> None:
    assert multiline_block(keystrokes) is refused


def test_send_keys_command_shape() -> None:
    """Targets are exact-match (`=`), `--` keeps dash keystrokes out of option parsing, and the lone `;` tmux would consume as a command separator goes as hex."""
    assert send_keys_command("s", ["-la\n"]) == [
        "tmux",
        "send-keys",
        "-t",
        "=s:",
        "--",
        "-la\n",
    ]
    # a semicolon-terminated argument is unsendable, not silently repaired:
    # tmux would read it as a command separator and drop the character (or,
    # with a key after it, reject the whole command list and type nothing)
    with pytest.raises(ValueError, match="semicolon-terminated"):
        send_keys_command("s", [";"])
    with pytest.raises(ValueError, match="semicolon-terminated"):
        send_keys_command("s", ["echo x;", "Enter"])


def test_send_keys_commands_chunks_oversized_keys() -> None:
    """A tmux client command over ~16 KB fails ("command too long"), so an oversized key argument splits into literal `-l` chunks."""
    assert send_keys_commands("s", ["ls"]) == [send_keys_command("s", ["ls"])]
    big = "x" * (SEND_CHUNK_CHARS * 2 + 5)
    commands = send_keys_commands("s", [big, "Enter"])
    assert len(commands) == 4
    # the chunks are literal (`-l`: a chunk equal to a key name is typed, not
    # pressed) and reassemble to the original key argument
    assert all("-l" in command for command in commands[:3])
    assert "".join(command[-1] for command in commands[:3]) == big
    # the Enter key stays a key press, never a literal chunk
    assert commands[3] == send_keys_command("s", ["Enter"])


KEY_NAMES = ("Enter", "C-c", "Escape", "Space", "BSpace")


def typed_text(commands: list[list[str]]) -> str:
    r"""The characters tmux types for a command sequence, modelling its semicolon rule.

    Replaying what we MEANT to send would make the headline assertion below
    vacuous, because dropping a character is exactly the defect under test. So
    this models the behaviour measured on tmux 3.4 instead: an argument ending
    in `;` loses that one semicolon, and if a `\` is exposed underneath, tmux
    reads it as an escape and types a bare `;`.

    Key names on the lookup path are rejected rather than guessed at: tmux
    presses them, so no string of characters is the honest answer, and a future
    row like `Space;` must fail loudly instead of being replayed as five
    letters. On the literal (`-l`) path lookup is off, so the same string IS
    typed as its characters.
    """
    typed: list[str] = []
    for command in commands:
        if command[4] == "-H":
            typed.extend(chr(int(byte, 16)) for byte in command[5:])
            continue
        lookup = command[4] == "--"
        for argument in command[command.index("--") + 1 :]:
            if lookup and argument in KEY_NAMES:
                raise AssertionError(
                    f"typed_text cannot model the key name {argument!r}: tmux "
                    "presses it rather than typing characters"
                )
            if argument.endswith(";"):
                argument = argument[:-1]
                if argument.endswith("\\"):
                    argument = argument[:-1] + ";"
            typed.append(argument)
    return "".join(typed)


@pytest.mark.parametrize(
    "keystrokes",
    [
        "echo hi;",
        ";",
        ";;;",
        "a" * (SEND_CHUNK_CHARS - 1) + ";",
        "b" * SEND_CHUNK_CHARS + ";",
        # the measured shape: a chunk boundary falling just after a semicolon
        "c" * (SEND_CHUNK_CHARS - 1) + ";" + "d" * 50,
        "e" * (SEND_CHUNK_CHARS * 2 - 1) + ";f",
        # a run of semicolons straddling a boundary
        "g" * (SEND_CHUNK_CHARS - 1) + ";;;",
        # tmux eats the semicolon, then reads the exposed `\` as an escape
        "printf 'a\\;'",
        "find . -exec ls {} \\;",
        # char slicing, not byte slicing, keeps a codepoint whole at a boundary
        "\u00e9" * SEND_CHUNK_CHARS + ";",
    ],
    ids=lambda k: f"len{len(k)}",
)
def test_every_semicolon_reaches_the_pane(keystrokes: str) -> None:
    """Keystrokes arrive byte-exact however the chunking falls.

    tmux's client reads a semicolon that ends an argument as a command
    separator, `--` notwithstanding, so the character is dropped. Fixed-size
    chunking manufactures these out of ordinary input: a boundary landing just
    after a semicolon turned `int n=0;` into `int n=0` inside a heredoc in a
    real run, and the pane reported it as the agent's own syntax error.
    """
    commands = send_keys_commands("s", [keystrokes])
    for command in commands:
        if command[4] == "-H":
            continue
        # every argument, not just the last: tmux ends the command list at the
        # first one that terminates in a semicolon
        arguments = command[command.index("--") + 1 :]
        assert not any(argument.endswith(";") for argument in arguments)
    assert typed_text(commands) == keystrokes


def test_a_semicolon_terminated_key_does_not_swallow_the_key_after_it() -> None:
    """A key following a semicolon-terminated one must still be pressed.

    `send-keys -l -- 'echo x;' Enter` reports `unknown command: Enter`, and
    tmux rejects the command list before typing anything, so `echo x` never
    reaches the pane either and the Enter is never pressed.
    """
    commands = send_keys_commands("s", ["echo x;", "Enter"])
    assert commands[-1] == send_keys_command("s", ["Enter"])
    assert typed_text(commands[:-1]) == "echo x;"


def test_an_interior_semicolon_keeps_the_single_command_path() -> None:
    """Only a TERMINATING semicolon is tmux's separator, so a command line full of them still sends as one.

    Splitting on every semicolon would be the natural over-correction, and it
    would cost a round trip per semicolon on the most ordinary keystrokes there
    are.
    """
    keys, _ = prepare_send("s", "clear; echo one; echo two\n", False, "ab-7")
    commands = send_keys_commands("s", keys)
    assert len(commands) == 1
    assert typed_text(commands) == "clear; echo one; echo two\r"


def test_keys_without_trailing_semicolons_keep_the_single_command_path() -> None:
    """The common send is one tmux command, with key names still looked up."""
    assert send_keys_commands("s", ["echo hi", "Enter"]) == [
        send_keys_command("s", ["echo hi", "Enter"])
    ]


@pytest.mark.parametrize("word", ["up", "end", "space", "tab", "Up", "DELETE"])
def test_a_pasted_line_that_reads_as_a_key_name_is_typed_not_pressed(
    word: str,
) -> None:
    """Tmux key-name lookup is case-insensitive, so ordinary words are live keys.

    A pasted line reading `up` would press the up arrow, which in a shell
    recalls the previous line into whatever the paste was feeding. A wordlist
    or a one-column file would be corrupted silently and the agent would read
    the damage as its own. Any argument carrying a line break is therefore
    typed literally, where lookup is off.
    """
    keystrokes = f"alpha\n{word}\nomega\n"
    keys, _ = prepare_send("s", keystrokes, False, "ab-7")
    for command in send_keys_commands("s", keys):
        assert "-l" in command, f"{word!r} would be looked up as a key name"


@pytest.mark.parametrize("word", ["up", "home", "tab", "Enter", "C-c"])
def test_a_semicolon_terminated_key_name_is_typed_not_pressed(word: str) -> None:
    """A key name is honored only as the ENTIRE keystrokes value, and `up;` is not one.

    The semicolon split sent the remaining body through key-name lookup, so
    `up;` pressed the up arrow and recalled the previous shell line: the same
    silent corruption the line-break path guards against, reachable through a
    trailing semicolon instead.
    """
    commands = send_keys_commands("s", [f"{word};"])
    assert typed_text(commands) == f"{word};"
    for command in commands:
        assert command[4] in ("-l", "-H"), f"{word!r} would be looked up"


def test_a_multiline_paste_stays_under_the_tmux_command_limit() -> None:
    """Tmux rejects a client command over ~16 KB, so a big paste must still chunk.

    Splitting a paste into one argument per line would defeat the chunker,
    because its budget is per argument: thousands of short lines are each
    under the limit while the assembled command is far over it, and the send
    fails outright with "command too long".
    """
    keystrokes = "".join(f"line {index} of the pasted file\n" for index in range(600))
    assert len(keystrokes) > 16_000
    keys, _ = prepare_send("s", keystrokes, False, "ab-7")
    commands = send_keys_commands("s", keys)
    assert all(sum(len(part) for part in command) < 16_000 for command in commands)
    # and not at the cost of a round trip per line
    assert len(commands) < 20


def test_a_line_break_composes_with_the_semicolon_split() -> None:
    """The two keystroke fixes meet on the most ordinary shell line there is."""
    keys, _ = prepare_send("s", "echo hi;\n", False, "ab-7")
    assert keys == ["echo hi;\r"]
    assert typed_text(send_keys_commands("s", keys)) == "echo hi;\r"


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        # first read: no anchor
        (None, "screen", None),
        # single-line anchor: delta starts at the anchor
        ("$ ls", "$ ls\nfile-a\nfile-b", "$ ls\nfile-a\nfile-b"),
        # multiline anchor: delta starts at the anchor's final line
        ("$ ls\nfile-a", "$ ls\nfile-a\nfile-b", "\nfile-a\nfile-b"),
        # rotated past history or cleared: anchor lost, no delta claimed
        ("gone from scrollback", "fresh content", None),
        # empty previous buffer: nothing to anchor on
        ("", "anything", None),
    ],
)
def test_find_new_content(
    previous: str | None, current: str, expected: str | None
) -> None:
    assert find_new_content(previous, current) == expected


@pytest.mark.parametrize(
    ("new_content", "screen", "first_read", "expected_head"),
    [
        # a determinable delta returns raw, no header (viewer UX review 2026-10-23)
        ("\nfile-a", "ignored", False, "\nfile-a"),
        (None, "the screen", False, "Current Terminal Screen:"),
        # a whitespace-only delta reports the screen, not a blank delta
        ("   \n", "the screen", False, "Current Terminal Screen:"),
        # a session's FIRST read has no previously-seen screen to re-act on,
        # so the label is noise there (viewer UX review 2026-10-24); the
        # mid-session lost-anchor fallback above keeps it
        (None, "the screen", True, "the screen"),
        ("   \n", "the screen", True, "the screen"),
    ],
)
def test_label_output(
    new_content: str | None, screen: str, first_read: bool, expected_head: str
) -> None:
    assert label_output(new_content, screen, first_read=first_read).startswith(
        expected_head
    )


def test_clip_output_keeps_tail_and_marks() -> None:
    assert clip_output("short") == "short"
    long = "x" * (OUTPUT_CLIP_BYTES + 100) + "TAIL"
    clipped = clip_output(long)
    assert clipped.startswith("[output clipped")
    assert clipped.endswith("TAIL")
    assert len(clipped.encode()) < OUTPUT_CLIP_BYTES + 200


@pytest.mark.parametrize(
    ("command", "shell"),
    [
        ("bash", True),
        ("zsh\n", True),
        ("msfconsole", False),
        ("nc", False),
        ("python3", False),
        ("", False),
    ],
)
def test_is_shell(command: str, shell: bool) -> None:
    assert is_shell(command) is shell


def test_command_builders_shape() -> None:
    start = start_session_command("s")
    assert (
        start[0] == "bash"
        and "pipe-pane" in start[2]
        and "/tmp/.guestd/s.pipe" in start[2]
    )
    # the sink truncates at open: a reopened name must not replay its last life
    assert ": > /tmp/.guestd/s.pipe" in start[2]
    # history-limit applies only to windows created after it is set, so the
    # global raise must precede new-session (and be restored after)
    assert start[2].index("history-limit 50000") < start[2].index("new-session")
    assert capture_pane_command("s", entire=True)[:4] == [
        "tmux",
        "capture-pane",
        "-p",
        "-S",
    ]
    assert capture_pane_command("s")[-1] == "=s:"  # exact-match target
    wait = wait_done_command("s", 30.0, "ab-3")
    assert wait[:2] == ["timeout", "30.0s"] and wait[-1] == wait_channel("s", "ab-3")


def test_pane_sink_naming_round_trip() -> None:
    """A pane sink path carries the session, the life token, and the stable `%N` pane id; the parse recovers the id only for this life's sinks (the token discipline: a reopened name's new life must never pick up a dead life's panes)."""
    path = pane_sink_path("s", "ab12cd34", "%7")
    assert path == "/tmp/.guestd/s-ab12cd34-p%7.pipe"
    assert pane_id_from_sink(path, "s", "ab12cd34") == "%7"
    # another life's token, another session, the primary sink, and a
    # malformed pane id all parse to None
    assert pane_id_from_sink(path, "s", "ffffffff") is None
    assert pane_id_from_sink(path, "other", "ab12cd34") is None
    assert pane_id_from_sink("/tmp/.guestd/s.pipe", "s", "ab12cd34") is None
    assert pane_id_from_sink("/tmp/.guestd/s-ab12cd34-pbad.pipe", "s", "ab12cd34") is (
        None
    )
    assert pane_label("%12") == "p12"


def test_pane_sink_glob_is_token_exact() -> None:
    import fnmatch

    glob = pane_sink_glob("s", "ab12cd34")
    assert fnmatch.fnmatch(pane_sink_path("s", "ab12cd34", "%3"), glob)
    # a dead life's sinks (different token) never match the new life's glob
    assert not fnmatch.fnmatch(pane_sink_path("s", "ffffffff", "%3"), glob)
    # nor does the primary sink, or a longer session name sharing the prefix
    assert not fnmatch.fnmatch("/tmp/.guestd/s.pipe", glob)
    assert not fnmatch.fnmatch(pane_sink_path("s-2", "ab12cd34", "%3"), glob)


def test_set_pane_hooks_commands_shape() -> None:
    """Both window-creation hooks install as separate session-scoped argv commands: the hook argument embeds the life token in the sink and expands `#{pane_id}` at fire time, and carries no semicolon for tmux's config parser to misread."""
    commands = set_pane_hooks_commands("s", "ab12cd34")
    hooks = [command[4] for command in commands]
    assert hooks == ["after-new-window", "after-split-window"]
    for command in commands:
        assert command[:4] == ["tmux", "set-hook", "-t", "=s:"]
        hook_command = command[5]
        assert hook_command == (
            "pipe-pane 'cat >> /tmp/.guestd/s-ab12cd34-p#{pane_id}.pipe'"
        )
        assert ";" not in hook_command
    # a new life re-sets the hooks with its own token, so a reopened name
    # cannot append onto a dead life's pane sink
    assert set_pane_hooks_commands("s", "ffffffff") != commands
    # the rollback commands unset exactly the same hooks, session-scoped
    from inspect_ranges._terminal.session import unset_pane_hooks_commands

    assert unset_pane_hooks_commands("s") == [
        ["tmux", "set-hook", "-u", "-t", "=s:", hook] for hook in hooks
    ]


def test_remove_sink_command_covers_pane_sinks() -> None:
    """Close removes the primary sink and the life's per-pane sinks in one pass; the glob is token-exact, so a concurrently open life of another name is untouched."""
    command = remove_sink_command("s", "ab12cd34")
    assert command[:2] == ["sh", "-c"]
    assert "/tmp/.guestd/s.pipe" in command[2]
    assert pane_sink_glob("s", "ab12cd34") in command[2]


def test_assemble_cast_orders_and_offsets_events() -> None:
    cast = assemble_cast(
        chunks=[(102.0, b"out-late"), (100.5, b"out-early")],
        markers=[(100.5, "send: ls"), (99.0, "open")],
        start_monotonic=100.0,
        start_wall=1_700_000_000.25,
        title="s",
    )
    lines = cast.strip().split("\n")
    header = json.loads(lines[0])
    assert header["version"] == 2 and header["width"] == 160 and header["title"] == "s"
    events = [json.loads(line) for line in lines[1:]]
    # the pre-start marker clamps to zero; at equal times the marker precedes output
    assert events[0] == [0.0, "m", "open"]
    assert events[1] == [0.5, "m", "send: ls"]
    assert events[2] == [0.5, "o", "out-early"]
    assert events[3] == [2.0, "o", "out-late"]


def test_assemble_cast_carries_opener_identity_in_the_header() -> None:
    """`ir_*` header fields are additive (parsers ignore unknown keys): present when the opener is known, absent otherwise, so older casts present flat and older players stay unaffected."""
    from inspect_ranges._terminal.cast import SessionOpener

    cast = assemble_cast(
        chunks=[],
        markers=[(100.0, "open")],
        start_monotonic=100.0,
        start_wall=1_700_000_000.0,
        title="terminal session main",
        session="main",
        opener=SessionOpener(
            agent_span_id="span-abc", agent_name="researcher", tool_span_id="span-def"
        ),
    )
    header = json.loads(cast.split("\n", 1)[0])
    assert header["ir_session"] == "main"
    assert header["ir_agent_span_id"] == "span-abc"
    assert header["ir_agent"] == "researcher"
    assert header["ir_tool_span_id"] == "span-def"

    bare = assemble_cast(
        chunks=[],
        markers=[(100.0, "open")],
        start_monotonic=100.0,
        start_wall=1_700_000_000.0,
        title="s",
    )
    bare_header = json.loads(bare.split("\n", 1)[0])
    assert not any(key.startswith("ir_") for key in bare_header)

    unattributed = assemble_cast(
        chunks=[],
        markers=[],
        start_monotonic=100.0,
        start_wall=1_700_000_000.0,
        title="s",
        session="s",
        opener=SessionOpener(),
    )
    unattributed_header = json.loads(unattributed.split("\n", 1)[0])
    assert set(k for k in unattributed_header if k.startswith("ir_")) == {"ir_session"}


def test_scrub_harness_echo_removes_wait_suffix() -> None:
    echoed = "$ ls /opt; tmux wait -S done-main-b7f168f4-1\nguestd\n$"
    scrubbed = scrub_harness_echo(echoed)
    assert "tmux wait" not in scrubbed
    assert scrubbed.startswith("$ ls /opt\n")


_PREFIX = wait_channel_prefix("main", "b7f168f4")
_SUFFIX = "; tmux wait -S done-main-b7f168f4-12"


def capture_pane_render(logical: str) -> str:
    """One long logical line as `capture-pane` renders it.

    The wrap at `PANE_WIDTH` is only half of it: capture-pane also trims each
    line's trailing whitespace, so a wrap landing on a space ends that line one
    column short and the space is gone. Modelling the wrap without the trim is
    what hid this: the scrub's four space split points leaked into two agents'
    transcripts while the suite stayed green.
    """
    lines: list[str] = []
    while len(logical) > PANE_WIDTH:
        lines.append(logical[:PANE_WIDTH].rstrip(" "))
        logical = logical[PANE_WIDTH:]
    lines.append(logical)
    return "\n".join(lines)


@pytest.mark.parametrize("break_at", range(len(_SUFFIX) + 1))
def test_scrub_harness_echo_removes_wrapped_wait_suffix(break_at: int) -> None:
    """capture-pane inserts a newline where the pane wraps at 160 columns, and the wrap can fall between ANY two characters of the echoed signal (or just before it); every split point must scrub without leaking a fragment to the model (pre-ship P1-7)."""
    body = "$ echo " + "x" * (PANE_WIDTH - 7 - break_at)
    assert len(body) + break_at == PANE_WIDTH
    text = capture_pane_render(body + _SUFFIX) + "\nout-42\n$ "
    assert scrub_harness_echo(text, _PREFIX) == f"{body}\nout-42\n$ "


@pytest.mark.parametrize(
    "text",
    [
        # a lookalike broken at a non-wrap column is agent-authored text, kept
        "note; tmux wa\nit -S done-main-b7f168f4-3\n$ ",
        # another session's (or an agent-authored) channel is not ours
        "$ cat notes; tmux wait -S done-other-ffffffff-1\nkept\n$ ",
    ],
)
def test_scrub_harness_echo_keeps_lookalikes(text: str) -> None:
    """The scrub is anchored to our channel prefix and, for wrapped forms, to the wrap column, so text that merely resembles the signal survives byte-exact."""
    assert scrub_harness_echo(text, _PREFIX) == text


@pytest.mark.parametrize(
    ("break_column", "left_tail", "remainder", "scrubbed"),
    [
        # a wrap on the suffix's space: capture-pane trims it, one column short
        (PANE_WIDTH - 1, "; tmux wait", "-S ", True),
        # the trimmed form at full width is a line break the pane did not make
        # (its untrimmed line would be a column over the pane)
        (PANE_WIDTH, "; tmux wait", "-S ", False),
        (PANE_WIDTH - 2, "; tmux wait", "-S ", False),
        # the space surviving means nothing was trimmed: full width only
        (PANE_WIDTH, "; tmux wait ", "-S ", True),
        (PANE_WIDTH - 1, "; tmux wait ", "-S ", False),
        # a wrap inside a word can never be trimmed: full width only
        (PANE_WIDTH, "; tmux w", "ait -S ", True),
        (PANE_WIDTH - 1, "; tmux w", "ait -S ", False),
    ],
)
def test_scrub_harness_echo_requires_the_exact_wrap_column(
    break_column: int, left_tail: str, remainder: str, scrubbed: bool
) -> None:
    """The accepted wrap column is the pane width minus exactly the spaces the match lost to the trim.

    The column test is what keeps agent-authored text that resembles the
    signal from being eaten, so its width is a contract per split, not a
    blanket window. A window as wide as the worst split scrubs shapes no
    capture can produce, and it eats real output (the digit test below);
    a 40-column allowance even leaves every other test in this file green.
    """
    head = "x" * (break_column - len(left_tail)) + left_tail
    assert len(head) == break_column
    text = f"{head}\n{remainder}{_PREFIX}7\nout\n$ "
    expected = f"{head[: -len(left_tail)]}\nout\n$ " if scrubbed else text
    assert scrub_harness_echo(text, _PREFIX) == expected


def test_scrub_harness_echo_keeps_digit_output_after_a_short_suffix_line() -> None:
    """An echo line that simply ends in the channel digits short of the pane width is no wrap, and the output after it survives.

    Digits are never trimmed, so a line one column short cannot be a wrap
    inside them. The blanket one-column window read it as one anyway and ate
    the next line's leading digits, which is the first thing a `wc -c` or an
    exit-status echo prints; the suffix still comes off through the plain
    (unwrapped) form.
    """
    suffix = f"; tmux wait -S {_PREFIX}7"
    body = "x" * (PANE_WIDTH - 1 - len(suffix))
    text = f"{body}{suffix}\n1042\nout\n$ "
    assert scrub_harness_echo(text, _PREFIX) == f"{body}\n1042\nout\n$ "


def test_scrub_harness_echo_keeps_a_digit_led_line_after_a_full_width_suffix() -> None:
    """Output that merely STARTS with digits survives even at the one ambiguous column.

    A genuine wrap continuation line ends with the channel digits, because the
    signal's Enter follows them at once, so a next line carrying anything after
    its leading digits is output, not a wrap. Only an output line that is
    entirely digits after a full-width suffix line remains indistinguishable
    (the docstring records it).
    """
    suffix = f"; tmux wait -S {_PREFIX}7"
    body = "x" * (PANE_WIDTH - len(suffix))
    text = f"{body}{suffix}\n1042 rows\nout\n$ "
    assert scrub_harness_echo(text, _PREFIX) == f"{body}\n1042 rows\nout\n$ "


def test_scrub_harness_echo_anchored_still_removes_plain_form() -> None:
    echoed = f"$ ls /opt{_SUFFIX}\nguestd\n$"
    assert scrub_harness_echo(echoed, _PREFIX) == "$ ls /opt\nguestd\n$"


@pytest.mark.parametrize(
    ("cap_mb_env", "expected_mb"),
    [("", 50), ("200", 200), ("junk", 50), ("0", 1)],
)
def test_cast_store_cap_parses_with_fallback(
    monkeypatch: pytest.MonkeyPatch, cap_mb_env: str, expected_mb: int
) -> None:
    from inspect_ranges._terminal.cast import CAST_STORE_CAP_ENV, cast_store_cap_bytes

    if cap_mb_env:
        monkeypatch.setenv(CAST_STORE_CAP_ENV, cap_mb_env)
    else:
        monkeypatch.delenv(CAST_STORE_CAP_ENV, raising=False)
    assert cast_store_cap_bytes() == expected_mb * 1024 * 1024


def test_clip_cast_keeps_header_and_tail_with_a_marker() -> None:
    import json as json_module

    from inspect_ranges._terminal.cast import clip_cast

    header = json_module.dumps({"version": 2, "width": 80, "height": 24})
    events = [
        json_module.dumps([float(i), "o", f"line-{i:04d} " + "x" * 50])
        for i in range(100)
    ]
    cast = header + "\n" + "\n".join(events)
    clipped = clip_cast(cast, 2000)
    lines = clipped.split("\n")
    assert json_module.loads(lines[0])["version"] == 2, "the header survives"
    marker = json_module.loads(lines[1])
    assert marker[1] == "m" and "clipped" in marker[2]
    assert len(clipped.encode()) <= 2000 + len(lines[1])  # marker rides the budget
    for line in lines[2:]:
        event = json_module.loads(line)  # every kept line is a whole event
        assert event[1] == "o"
    assert "line-0099" in clipped and "line-0000" not in clipped, "tail kept, head cut"


def test_clip_cast_leaves_small_casts_alone() -> None:
    from inspect_ranges._terminal.cast import clip_cast

    cast = '{"version": 2}\n[0.1, "o", "hi"]'
    assert clip_cast(cast, 10_000) == cast


@pytest.mark.parametrize("cap", [0, 50, 150])
def test_clip_cast_exhausted_budget_keeps_only_header_and_marker(cap: int) -> None:
    """A cap the header and marker already exhaust clips a multi-event cast to exactly those two lines.

    The old tail slice used `[-max(budget, 0):]`, and `[-0:]` slices from the
    front: an exhausted budget returned the whole event stream (measured), so
    a sibling cast meant to be starved under the session's shared store cap
    leaked everything instead.
    """
    from inspect_ranges._terminal.cast import clip_cast

    header = json.dumps({"version": 2})
    events = [json.dumps([float(i), "o", "x" * 50]) for i in range(10)]
    cast = header + "\n" + "\n".join(events) + "\n"
    clipped = clip_cast(cast, cap)
    lines = clipped.strip().split("\n")
    assert json.loads(lines[0])["version"] == 2
    assert [json.loads(line)[1] for line in lines[1:]] == ["m"]
    assert "x" * 50 not in clipped


def test_clip_cast_budget_below_one_event_still_stubs() -> None:
    """A budget that fits the marker but not even one whole event line keeps no partial line: the result is still the header-and-marker stub, never a truncated JSON event."""
    from inspect_ranges._terminal.cast import clip_cast

    header = json.dumps({"version": 2})
    events = [json.dumps([float(i), "o", "x" * 200]) for i in range(5)]
    cast = header + "\n" + "\n".join(events) + "\n"
    # past the stub (~header+marker) but short of any whole 200-char event
    clipped = clip_cast(cast, 300)
    lines = clipped.strip().split("\n")
    assert [json.loads(line)[1] for line in lines[1:]] == ["m"]
    assert len(clipped.encode()) <= 300 + 200  # marker overhead only


@pytest.mark.parametrize(
    ("version", "supported"),
    [
        ("tmux 3.4", True),
        ("tmux 3.5a", True),
        ("tmux next-3.6", True),
        ("tmux 10.0", True),
        ("tmux 3.3a", False),
        ("tmux 2.9", False),
        ("tmux master", False),
        ("", False),
        ("no version here", False),
    ],
)
def test_pane_hooks_supported_fails_closed(version: str, supported: bool) -> None:
    """The hook gate: proven (3.4) and later versions pass; an older or unparseable `tmux -V` fails closed, because an unproven hook context could divert the primary tap."""
    from inspect_ranges._terminal.session import pane_hooks_supported

    assert pane_hooks_supported(version) is supported


_SPLIT_STREAM = f"$ ls /opt{_SUFFIX}\r\nguestd\r\n$ "


@pytest.mark.parametrize("split", [0, 9, 12, 20, len(_SUFFIX) + 8, len(_SPLIT_STREAM)])
def test_assemble_cast_scrubs_wait_echo_across_chunks(split: int) -> None:
    """The echoed completion signal is removed from the cast's output stream wherever the chunk boundary falls (before, inside, or after it); surviving bytes keep their chunk, so their timestamp, and an emptied chunk is dropped."""
    from inspect_ranges._terminal.cast import scrub_stream

    chunks = [
        (100.5, _SPLIT_STREAM[:split].encode()),
        (101.0, _SPLIT_STREAM[split:].encode()),
    ]
    cast = assemble_cast(
        chunks=chunks,
        markers=[],
        start_monotonic=100.0,
        start_wall=1_700_000_000.0,
        title="s",
        channel_prefix=_PREFIX,
    )
    events = [json.loads(line) for line in cast.strip().split("\n")[1:]]
    assert "".join(data for _, _, data in events) == "$ ls /opt\r\nguestd\r\n$ "
    assert all(data for _, _, data in events)
    expected = [
        t
        for t, text in zip(
            [0.5, 1.0],
            scrub_stream([_SPLIT_STREAM[:split], _SPLIT_STREAM[split:]], _PREFIX),
            strict=True,
        )
        if text
    ]
    assert [t for t, _, _ in events] == expected


def test_assemble_cast_scrubs_every_send_but_keeps_lookalikes() -> None:
    """Each blocking send carries its own counter; all of them scrub, while another channel's (or agent-authored) signal is not ours and stays."""
    stream = (
        "$ id; tmux wait -S done-main-b7f168f4-1\r\nuid=0\r\n"
        "$ cat notes; tmux wait -S done-other-ffffffff-1\r\nkept\r\n"
        "$ ls; tmux wait -S done-main-b7f168f4-2\r\n$ "
    )
    cast = assemble_cast(
        chunks=[(100.0, stream.encode())],
        markers=[],
        start_monotonic=100.0,
        start_wall=1_700_000_000.0,
        title="s",
        channel_prefix=_PREFIX,
    )
    _, _, data = json.loads(cast.strip().split("\n")[1])
    assert data == (
        "$ id\r\nuid=0\r\n"
        "$ cat notes; tmux wait -S done-other-ffffffff-1\r\nkept\r\n"
        "$ ls\r\n$ "
    )


def test_assemble_cast_without_prefix_keeps_the_raw_stream() -> None:
    stream = f"$ ls{_SUFFIX}\r\n$ "
    cast = assemble_cast(
        chunks=[(100.0, stream.encode())],
        markers=[],
        start_monotonic=100.0,
        start_wall=1_700_000_000.0,
        title="s",
    )
    assert json.loads(cast.strip().split("\n")[1])[2] == stream
