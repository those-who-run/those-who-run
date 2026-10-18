from pathlib import Path

from those_who_run.__main__ import build_parser


def test_run_accepts_record_flag():
    args = build_parser().parse_args(["run", "--record", "out.jsonl"])
    assert args.command == "run" and args.record == Path("out.jsonl")
    assert build_parser().parse_args(["run"]).record is None


def test_say_has_default_text():
    args = build_parser().parse_args(["say"])
    assert args.command == "say" and "Radio check" in args.text
    assert build_parser().parse_args(["say", "hello"]).text == "hello"


def test_replay_and_record_subcommands():
    r = build_parser().parse_args(["replay", "x.jsonl", "--wav-out", "o"])
    assert r.recording == Path("x.jsonl") and r.wav_out == Path("o")
    c = build_parser().parse_args(["record", "y.jsonl", "--ps5-ip", "1.2.3.4", "--seconds", "30"])
    assert c.ps5_ip == "1.2.3.4" and c.seconds == 30


def test_thin_subcommand():
    t = build_parser().parse_args(
        ["thin", "in.jsonl.gz", "out.jsonl", "--start", "10", "--end", "95"]
    )
    assert t.source == Path("in.jsonl.gz") and t.output == Path("out.jsonl")
    assert (t.start, t.end, t.every) == (10, 95, 0.5)


def test_each_command_is_a_module_in_the_one_table():
    """#171: a command is ``cli/<command>.py`` with configure and run, listed in COMMANDS."""
    import those_who_run.__main__ as entry
    from those_who_run.cli import COMMANDS

    package = Path(entry.__file__).with_name("cli")
    for name, command in COMMANDS.items():
        assert Path(command.__file__) == package / f"{name.replace('-', '_')}.py"
        assert callable(command.configure) and callable(command.run) and command.HELP
    choices = build_parser()._subparsers._group_actions[0].choices
    assert list(choices) == list(COMMANDS)
    assert len(Path(entry.__file__).read_text().splitlines()) < 50
