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
