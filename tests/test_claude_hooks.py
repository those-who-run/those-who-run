"""The commit hooks and Claude Code's guard (#339).

`.claude/hooks/guard.py` is tested as Claude Code runs it: hook input JSON on stdin,
the verdict as the exit code (2 blocks, the reason on stderr) or as JSON on stdout
(`permissionDecision: "ask"`). Each rule has a blocked example and a near miss that
passes.
"""

import importlib.util
import io
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / ".claude" / "hooks" / "guard.py"

_spec = importlib.util.spec_from_file_location("claude_guard", GUARD)
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
sys.modules["claude_guard"] = guard  # dataclasses look their module up
_spec.loader.exec_module(guard)


def hook_input(command, tool="Bash"):
    """What Claude Code sends a PreToolUse hook (https://code.claude.com/docs/en/hooks)."""
    return {
        "session_id": "abc123",
        "transcript_path": "/home/user/.claude/projects/x/transcript.jsonl",
        "cwd": str(ROOT),
        "permission_mode": "auto",
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": {"command": command, "description": "test"},
        "tool_use_id": "toolu_01",
    }


def run(payload):
    """The guard's (exit code, stdout, stderr) for a hook input, as Claude Code sees them."""
    stdin = io.StringIO(payload if isinstance(payload, str) else json.dumps(payload))
    out, err = io.StringIO(), io.StringIO()
    code = guard.main(stdin, out, err)
    return code, out.getvalue(), err.getvalue()


def decision(command):
    code, out, err = run(hook_input(command))
    if code == 2:
        assert err.startswith("blocked by .claude/hooks/guard.py"), err
        return "block"
    assert code == 0 and not err
    if out:
        hso = json.loads(out)["hookSpecificOutput"]
        assert hso["hookEventName"] == "PreToolUse"
        assert hso["permissionDecisionReason"]
        return hso["permissionDecision"]
    return "allow"


# (blocked, near miss) pairs: the first must be blocked, the second must not be.
NO_VERIFY = [
    ('git commit --no-verify -m "x"', 'git commit -m "x"'),
    ('git commit -nm "x"', 'git commit -m "fix: the -n flag"'),
    ('git commit -n -m "x"', 'git commit -m "-n"'),
    ('git commit -am "x" -n', 'git commit -am "x"'),
    ("git commit --no-veri -m x", "git commit --verbose -m x"),
    ('git -C . commit --no-verify -m "x"', 'git -C . commit -m "x"'),
    ("/usr/bin/git commit -n -m x", "/usr/bin/git commit -m x"),
    ('SKIP=ruff git commit -m "x"', 'FOO=1 git commit -m "x"'),
    ("export SKIP=ruff; git commit -m x", "export FOO=1; git commit -m x"),
    ("env SKIP=ruff git commit -m x", "env FOO=1 git commit -m x"),
    ("git merge --no-verify feat/x", "git merge feat/x"),
    ("git push --no-verify origin feat/x", "git push origin feat/x"),
    ("git -c core.hooksPath=/dev/null commit -m x", "git -c user.name=x commit -m x"),
    ("git config core.hooksPath /tmp/none", "git config --get core.hooksPath"),
    ("pre-commit uninstall", "pre-commit run --all-files"),
    ('git commit -m "x" && git commit -n -m "y"', 'git commit -m "x" && git log -n 1'),
    ("bash -c 'git commit -n -m x'", "bash -c 'git log -n 1'"),
    ('sh -lc "git commit --no-verify -m x"', 'sh -lc "git status"'),
    ('echo "$(git commit -n -m x)"', 'echo "$(git log -n 1)"'),
    ("echo `git commit -n -m x`", "echo `git log -n 1`"),
    ("eval 'git commit -n -m x'", "eval 'git status'"),
    ("bash <<EOF\ngit commit -n -m x\nEOF", "cat <<EOF > notes.txt\ngit commit -n -m x\nEOF"),
    ("sudo -u me git commit -n -m x", "sudo -u me git log -n 1"),
    ("xargs -I{} git commit -n -m {}", "xargs -n1 echo"),
    ("timeout 60 git commit -n -m x", "timeout 60 make check"),
    ("uv run git commit -n -m x", "uv run pytest -q"),
    ("cd web && git commit -n -m x", "cd web && npm test"),
    ("git commit \\\n  --no-verify -m x", "git commit \\\n  -m x"),
]


@pytest.mark.parametrize(("blocked", "near_miss"), NO_VERIFY)
def test_skipping_the_hooks_is_blocked(blocked, near_miss):
    assert decision(blocked) == "block"
    assert decision(near_miss) == "allow"


@pytest.mark.parametrize(
    "command",
    [
        'git commit -m "docs: never pass --no-verify"',
        "git commit -m --no-verify",
        'git commit -m "x" # --no-verify',
        "git commit -F- <<'EOF'\nfix: SKIP=ruff and -n are blocked\nEOF",
        # A PR body written with a here-document inside $(...), apostrophes and all.
        'gh pr create --title "feat: x" --body "$(cat <<\'EOF\'\n'
        "Don't pass git commit --no-verify; it's blocked (see #339).\nEOF\n)\"",
    ],
)
def test_text_that_mentions_the_flags_is_allowed(command):
    assert decision(command) == "allow"


def test_a_command_it_cannot_parse_asks_when_it_names_git():
    assert decision("git commit -m 'unterminated") == "ask"
    assert decision("ls 'unterminated") == "allow"


def test_a_program_in_a_variable_asks_when_it_names_git():
    assert decision('$GIT commit -n -m "git"') == "ask"
    assert decision('"$PY" scripts/openapi.py --check') == "allow"


def test_nesting_beyond_the_limit_asks():
    command = "git commit -n -m x"
    for _ in range(guard.MAX_DEPTH + 1):
        command = f"bash -c {json.dumps(command)}"
    assert decision(command) == "ask"


def test_a_shell_reading_a_pipe_asks_when_it_names_git():
    assert decision("echo 'git commit -n -m x' | bash") == "ask"
    assert decision("echo 'ls' | bash") == "allow"


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        json.dumps({"tool_name": "Bash"}),
        json.dumps({"tool_name": "Bash", "tool_input": {"command": ["git"]}}),
    ],
)
def test_the_guard_fails_closed(payload):
    code, _, err = run(payload)
    assert code == 2
    assert "the guard failed" in err


def test_other_tools_pass():
    assert run(hook_input("ignored", tool="Read"))[0] == 0


def test_the_script_blocks_as_claude_code_runs_it():
    """The real process: exit 2 and the reason on stderr, or exit 0 and no output."""

    def proc(command):
        return subprocess.run(
            [sys.executable, str(GUARD)],
            input=json.dumps(hook_input(command)),
            capture_output=True,
            text=True,
            check=False,
        )

    blocked = proc('git commit --no-verify -m "x"')
    assert blocked.returncode == 2
    assert "--no-verify skips the hooks" in blocked.stderr
    assert "ask the maintainer" in blocked.stderr
    allowed = proc('git commit -m "fix: the -n flag"')
    assert (allowed.returncode, allowed.stdout, allowed.stderr) == (0, "", "")


def test_settings_run_the_guard_on_bash_and_block_when_it_fails():
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text())
    [entry] = [e for e in settings["hooks"]["PreToolUse"] if e["matcher"] == "Bash"]
    [hook] = entry["hooks"]
    assert hook["type"] == "command"
    assert hook["onFailure"] == "block"  # a crash or a timeout blocks, never allows
    assert hook["args"] == ["${CLAUDE_PROJECT_DIR}/.claude/hooks/guard.py"]


def test_gitignore_tracks_the_settings_and_the_guard_but_not_the_worktrees():
    def ignored(path):
        r = subprocess.run(["git", "check-ignore", "--no-index", "-q", path], cwd=ROOT, check=False)
        return r.returncode == 0

    assert ignored(".claude/worktrees/agent-x/README.md")
    assert ignored(".claude/settings.local.json")
    assert not ignored(".claude/settings.json")
    assert not ignored(".claude/hooks/guard.py")


def test_external_hooks_are_pinned_to_a_commit():
    config = (ROOT / ".pre-commit-config.yaml").read_text()
    revs = re.findall(r"^\s*rev: (\S+)(.*)$", config, re.M)
    assert revs
    for sha, comment in revs:
        assert re.fullmatch(r"[0-9a-f]{40}", sha), sha
        assert re.fullmatch(r"\s+# frozen: v\S+", comment), comment


def test_commit_types_are_release_pleases():
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    [hook] = [
        h for r in config["repos"] for h in r["hooks"] if h["id"] == "conventional-pre-commit"
    ]
    rp = json.loads((ROOT / "release-please-config.json").read_text())
    assert sorted(hook["args"]) == sorted(s["type"] for s in rp["changelog-sections"])
