#!/usr/bin/env python3
"""Claude Code's PreToolUse guard on Bash for this repository (#339).

Claude Code runs it before every Bash command an agent sends (`.claude/settings.json`)
with the hook input as JSON on stdin. It never runs in the maintainer's own shell.
Permission rules match the command's text and are easy to sidestep (`git -C . commit`,
`bash -c '...'`), so this parses the command the way a shell would: it splits `;`,
`&&`, `||`, `|` and newlines, follows `$(...)`, backquotes, `bash -c`, `eval`, here-
documents fed to a shell, `env`/`VAR=` prefixes and wrappers such as `sudo` or
`xargs`, and then checks each simple command against the rules below.

  * block (exit 2, the reason on stderr): the agent is told why and to ask the
    maintainer;
  * ask (JSON `permissionDecision: "ask"`): the maintainer is asked before it runs;
  * nothing: Claude Code's own permission rules decide.

It fails closed: if the guard itself errors, the command is blocked, and a command
it can't follow that names one of the guarded programs is sent to `ask`.

Run it on a command to see the verdict:

    echo '{"tool_name": "Bash", "tool_input": {"command": "git commit -n"}}' \\
        | python3 .claude/hooks/guard.py

Plain Python 3.9+, standard library only: it runs before any `.venv` exists.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field

ALLOW, ASK, BLOCK = 0, 1, 2

# How deep `bash -c`, `eval` and `$(...)` are followed before the guard gives up and asks.
MAX_DEPTH = 3

# A command the guard can't follow is sent to `ask` when it names one of these.
SENSITIVE = re.compile(r"(?<![\w.-])(git|gh|kubectl|oc|helm|docker|podman|pre-commit)(?![\w-])")

ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish"}
# Shell keywords that may start a simple command and run what follows.
KEYWORDS = {"!", "{", "}", "if", "then", "else", "elif", "do", "while", "until", "time"}
# Programs that run the command named in their arguments.
WRAPPERS = {
    "sudo", "doas", "nice", "ionice", "nohup", "timeout", "stdbuf", "command", "builtin",
    "exec", "xargs", "watch", "setsid", "chronic", "unbuffer", "flock", "caffeinate",
    "strace", "ltrace", "unshare", "chroot", "runuser",
}  # fmt: skip


@dataclass(frozen=True)
class Verdict:
    level: int
    rule: str = ""
    reason: str = ""


ALLOWED = Verdict(ALLOW)


def block(rule: str, reason: str) -> Verdict:
    return Verdict(BLOCK, rule, reason)


def ask(rule: str, reason: str) -> Verdict:
    return Verdict(ASK, rule, reason)


def worst(verdicts: list[Verdict]) -> Verdict:
    """The strictest verdict; the first of equals, so the reason is the earliest."""
    out = ALLOWED
    for v in verdicts:
        if v.level > out.level:
            out = v
    return out


# ---------------------------------------------------------------------------
# The rules. Each takes a program's arguments (after its name) and the environment
# the command runs with, and returns a verdict. The tables are the policy: a new rule
# is a line here and a test in tests/test_claude_hooks.py.
# ---------------------------------------------------------------------------

HOOKS_SKIP = (
    "the commit hooks (.pre-commit-config.yaml) must run, and CI runs them anyway; "
    "fix what they report instead"
)


def long_option(arg: str, names: set[str] | tuple[str, ...], min_len: int = 4) -> str | None:
    """The long option in `names` that `arg` spells, allowing git's unique prefixes."""
    name = arg.split("=", 1)[0]
    if not name.startswith("--") or len(name) < min_len:
        return None
    for n in names:
        if n.startswith(name):
            return n
    return None


def short_flags(arg: str, with_value: str, optional_value: str = "") -> set[str]:
    """The flags in a short-option cluster such as `-nm`, up to one that takes a value."""
    if not arg.startswith("-") or arg.startswith("--") or len(arg) < 2:
        return set()
    out = set()
    for c in arg[1:]:
        out.add(c)
        if c in with_value or c in optional_value:
            break
    return out


# git's options before the subcommand that take a separate value.
GIT_GLOBAL_WITH_VALUE = {
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
    "--config-env", "--attr-source",
}  # fmt: skip
# Subcommands whose --no-verify skips a hook.
GIT_NO_VERIFY = {"commit", "merge", "pull", "am", "rebase", "push", "cherry-pick", "revert"}
# git commit's options that take a separate value (long) or the rest of the cluster.
COMMIT_LONG_WITH_VALUE = {
    "--message", "--file", "--reuse-message", "--reedit-message", "--template",
    "--author", "--date", "--fixup", "--squash", "--cleanup", "--trailer",
    "--pathspec-from-file",
}  # fmt: skip
COMMIT_SHORT_WITH_VALUE = "mFCct"
COMMIT_SHORT_OPTIONAL = "Su"


def hooks_path_override(key: str) -> bool:
    return key.strip().lower() == "core.hookspath"


def git_rule(args: list[str], env: dict[str, str]) -> Verdict:
    i = 0
    while i < len(args):
        a = args[i]
        if a in GIT_GLOBAL_WITH_VALUE and i + 1 < len(args):
            value = args[i + 1]
            if a in ("-c", "--config-env") and hooks_path_override(value.split("=", 1)[0]):
                return block(
                    "git-hooks-path", f"overriding core.hooksPath skips the hooks: {HOOKS_SKIP}"
                )
            i += 2
            continue
        if a.startswith("--config-env=") and hooks_path_override(a.split("=", 2)[1]):
            return block(
                "git-hooks-path", f"overriding core.hooksPath skips the hooks: {HOOKS_SKIP}"
            )
        if a.startswith("-"):
            i += 1
            continue
        break
    if i >= len(args):
        return ALLOWED
    for k, v in env.items():
        if (k.startswith("GIT_CONFIG_KEY_") and hooks_path_override(v)) or (
            k == "GIT_CONFIG_PARAMETERS" and "core.hookspath" in v.lower()
        ):
            return block(
                "git-hooks-path", f"overriding core.hooksPath skips the hooks: {HOOKS_SKIP}"
            )
    sub, rest = args[i], args[i + 1 :]
    verdicts = []
    if sub in GIT_NO_VERIFY:
        verdicts.append(git_no_verify(sub, rest, env))
    rule = GIT_RULES.get(sub)
    if rule is not None:
        verdicts.append(rule(rest, env))
    return worst(verdicts)


def takes_value(arg: str, long_with_value: set[str], short_with_value: str) -> bool:
    """Whether the argument after `arg` is its value: `-m`, `-am`, `--message`."""
    if arg in long_with_value:
        return True
    flags = short_flags(arg, short_with_value)
    return bool(flags) and arg[-1] in short_with_value


def git_no_verify(sub: str, args: list[str], env: dict[str, str]) -> Verdict:
    for i, a in enumerate(args):
        if a == "--":
            break
        commit = sub == "commit"
        if (
            commit
            and i > 0
            and takes_value(args[i - 1], COMMIT_LONG_WITH_VALUE, COMMIT_SHORT_WITH_VALUE)
        ):
            continue  # the previous option's value, such as -m's message
        if long_option(a, ("--no-verify",), min_len=len("--no-veri")):
            return block("git-no-verify", f"git {sub} --no-verify skips the hooks: {HOOKS_SKIP}")
        if commit and "n" in short_flags(a, COMMIT_SHORT_WITH_VALUE, COMMIT_SHORT_OPTIONAL):
            return block("git-no-verify", f"git commit -n skips the hooks: {HOOKS_SKIP}")
    if sub == "commit" and "SKIP" in env:
        return block("git-skip", f"SKIP= turns hooks off for a commit: {HOOKS_SKIP}")
    return ALLOWED


def git_config_rule(args: list[str], env: dict[str, str]) -> Verdict:
    reads = {"--get", "--get-all", "--get-regexp", "--list", "-l", "get", "list"}
    if any(hooks_path_override(a) for a in args) and not reads.intersection(args):
        return block("git-hooks-path", f"setting core.hooksPath moves the hooks away: {HOOKS_SKIP}")
    return ALLOWED


GIT_RULES = {
    "config": git_config_rule,
}


def pre_commit_rule(args: list[str], env: dict[str, str]) -> Verdict:
    if args[:1] == ["uninstall"]:
        return block("pre-commit-uninstall", f"uninstalling the hooks skips them: {HOOKS_SKIP}")
    return ALLOWED


# Program name -> rule. Programs are matched by their base name, so `/usr/bin/git`
# is `git`.
RULES = {
    "git": git_rule,
    "pre-commit": pre_commit_rule,
}


# ---------------------------------------------------------------------------
# Parsing: enough of the shell's grammar to find every simple command.
# ---------------------------------------------------------------------------


class ParseError(Exception):
    pass


@dataclass
class Token:
    kind: str  # "word", "op" or "redir"
    text: str
    subs: list[str] = field(default_factory=list)  # $(...), `...` and <(...) inside it
    heredoc: str | None = None  # the body of a << here-document


@dataclass
class Command:
    words: list[str] = field(default_factory=list)
    subs: list[str] = field(default_factory=list)
    stdin_scripts: list[str] = field(default_factory=list)  # here-documents and <<< strings


OPERATORS = ("&&", "||", ";;", "|&", ";", "|", "&", "(", ")")
REDIRECTIONS = ("<<<", "<<-", "<<", "&>>", "&>", ">>", ">&", "<&", "<>", ">|", ">", "<")


# A here-document's start: `<<EOF`, `<<-EOF`, `<< 'EOF'`, `<<"EOF"`, `<<\EOF`.
HEREDOC = re.compile(r"<<(-?)[ \t]*(?:'([^'\n]*)'|\"([^\"\n]*)\"|\\?([^\s;&|<>()'\"]+))")


def skip_heredoc_bodies(text: str, i: int, pending: list[tuple[str, bool]]) -> int:
    """The index after the bodies of the pending here-documents, which start at i."""
    for delim, strip_tabs in pending:
        while i < len(text):
            end = text.find("\n", i)
            line = text[i:] if end < 0 else text[i:end]
            i = len(text) if end < 0 else end + 1
            if (line.lstrip("\t") if strip_tabs else line) == delim:
                break
    pending.clear()
    return i


def read_balanced(text: str, i: int) -> tuple[str, int]:
    """The text from i up to the `)` that closes an already opened `(`, and the index
    after it. Quotes, backslashes and here-document bodies are skipped over, so an
    apostrophe in `"$(cat <<'EOF' ... EOF)"` doesn't open a quote."""
    depth, start = 1, i
    pending: list[tuple[str, bool]] = []
    while i < len(text):
        c = text[i]
        if c == "\n" and pending:
            i = skip_heredoc_bodies(text, i + 1, pending)
            continue
        if c == "<" and not text.startswith("<<<", i):
            m = HEREDOC.match(text, i)
            if m:
                delim = next(g for g in m.group(2, 3, 4) if g is not None)
                pending.append((delim, m.group(1) == "-"))
                i = m.end()
                continue
        if c == "\\":
            i += 2
            continue
        if c == "'":
            end = text.find("'", i + 1)
            if end < 0:
                raise ParseError("unterminated '")
            i = end + 1
            continue
        if c == '"':
            i = skip_double_quoted(text, i + 1)
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
        i += 1
    raise ParseError("unterminated (")


def skip_double_quoted(text: str, i: int) -> int:
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == '"':
            return i + 1
        if text.startswith("$(", i):
            _, i = read_balanced(text, i + 2)
            continue
        i += 1
    raise ParseError('unterminated "')


def read_backquoted(text: str, i: int) -> tuple[str, int]:
    out = []
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            out.append(text[i + 1])
            i += 2
            continue
        if c == "`":
            return "".join(out), i + 1
        out.append(c)
        i += 1
    raise ParseError("unterminated `")


def substitutions(text: str) -> list[str]:
    """The $(...) and `...` in text where quotes mean nothing (an unquoted here-document)."""
    subs, i = [], 0
    while i < len(text):
        if text.startswith("$(", i):
            inner, i = read_balanced(text, i + 2)
            subs.append(inner)
        elif text[i] == "`":
            inner, i = read_backquoted(text, i + 1)
            subs.append(inner)
        elif text[i] == "\\":
            i += 2
        else:
            i += 1
    return subs


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    word: list[str] = []
    subs: list[str] = []
    in_word = False
    quoted = False  # whether the current word has quotes or backslashes in it
    pending: list[tuple[Token, str, bool, bool]] = []  # here-documents awaiting a body
    expect_delimiter: Token | None = None
    i, n = 0, len(text)

    def end_word() -> None:
        nonlocal word, subs, in_word, quoted, expect_delimiter
        if in_word:
            tok = Token("word", "".join(word), subs)
            if expect_delimiter is not None:
                strip_tabs = expect_delimiter.text == "<<-"
                pending.append((expect_delimiter, tok.text, strip_tabs, quoted))
                expect_delimiter = None
            else:
                tokens.append(tok)
        word, subs, in_word, quoted = [], [], False, False

    def read_heredocs(i: int) -> int:
        for tok, delim, strip_tabs, delim_quoted in pending:
            body = []
            while i < n:
                end = text.find("\n", i)
                line = text[i:] if end < 0 else text[i:end]
                i = n if end < 0 else end + 1
                if (line.lstrip("\t") if strip_tabs else line) == delim:
                    break
                body.append(line)
            tok.heredoc = "\n".join(body)
            if not delim_quoted:
                tok.subs.extend(substitutions(tok.heredoc))
        pending.clear()
        return i

    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n and text[i + 1] == "\n":
            i += 2
            continue
        if c in " \t\r":
            end_word()
            i += 1
            continue
        if c == "\n":
            end_word()
            tokens.append(Token("op", "\n"))
            i = read_heredocs(i + 1)
            continue
        if c == "#" and not in_word:
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        if c in "<>" or (c == "&" and text.startswith("&>", i)):
            if c in "<>" and text.startswith("(", i + 1):
                inner, i = read_balanced(text, i + 2)
                subs.append(inner)
                in_word = True
                continue
            if in_word and "".join(word).isdigit():
                word, in_word = [], False  # a file descriptor, such as 2>
            end_word()
            op = next(r for r in REDIRECTIONS if text.startswith(r, i))
            tok = Token("redir", op)
            tokens.append(tok)
            if op in ("<<", "<<-"):
                expect_delimiter = tok
            i += len(op)
            continue
        if not in_word or c in ";|&()":
            op = next((o for o in OPERATORS if text.startswith(o, i)), None)
            if op is not None:
                end_word()
                tokens.append(Token("op", op))
                i += len(op)
                continue
        in_word = True
        if c in "\\'\"" or text.startswith("$'", i):
            quoted = True
        if c == "\\":
            if i + 1 < n:
                word.append(text[i + 1])
            i += 2
        elif c == "'":
            end = text.find("'", i + 1)
            if end < 0:
                raise ParseError("unterminated '")
            word.append(text[i + 1 : end])
            i = end + 1
        elif c == "$" and text.startswith("$'", i):
            j = i + 2
            while j < n and text[j] != "'":
                j += 2 if text[j] == "\\" else 1
            if j >= n:
                raise ParseError("unterminated $'")
            word.append(text[i + 2 : j])
            i = j + 1
        elif c == '"':
            j = i + 1
            while True:
                if j >= n:
                    raise ParseError('unterminated "')
                d = text[j]
                if d == '"':
                    break
                if d == "\\" and j + 1 < n:
                    if text[j + 1] in '"\\$`':
                        word.append(text[j + 1])
                    elif text[j + 1] != "\n":
                        word.append(text[j : j + 2])
                    j += 2
                elif text.startswith("$(", j):
                    inner, k = read_balanced(text, j + 2)
                    subs.append(inner)
                    word.append(text[j:k])
                    j = k
                elif d == "`":
                    inner, k = read_backquoted(text, j + 1)
                    subs.append(inner)
                    word.append(text[j:k])
                    j = k
                else:
                    word.append(d)
                    j += 1
            i = j + 1
        elif text.startswith("$(", i):
            inner, k = read_balanced(text, i + 2)
            subs.append(inner)
            word.append(text[i:k])
            i = k
        elif c == "`":
            inner, k = read_backquoted(text, i + 1)
            subs.append(inner)
            word.append(text[i:k])
            i = k
        else:
            word.append(c)
            i += 1
    end_word()
    if expect_delimiter is not None:
        raise ParseError("<< without a delimiter")
    read_heredocs(n)
    return tokens


def parse(text: str) -> list[Command]:
    """The simple commands in a shell script, in order."""
    commands, cmd = [], Command()
    tokens = tokenize(text)
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.kind == "op":
            if cmd.words or cmd.subs or cmd.stdin_scripts:
                commands.append(cmd)
            cmd = Command()
        elif tok.kind == "redir":
            cmd.subs.extend(tok.subs)
            if tok.heredoc is not None:
                cmd.stdin_scripts.append(tok.heredoc)
            elif i + 1 < len(tokens) and tokens[i + 1].kind == "word":
                i += 1
                cmd.subs.extend(tokens[i].subs)
                if tok.text == "<<<":
                    cmd.stdin_scripts.append(tokens[i].text)
        else:
            cmd.words.append(tok.text)
            cmd.subs.extend(tok.subs)
        i += 1
    if cmd.words or cmd.subs or cmd.stdin_scripts:
        commands.append(cmd)
    return commands


# ---------------------------------------------------------------------------
# Checking.
# ---------------------------------------------------------------------------


def ask_if_sensitive(text: str, why: str) -> Verdict:
    m = SENSITIVE.search(text)
    if m is None:
        return ALLOWED
    return ask("unparsed", f"the guard can't follow this command ({why}) and it runs {m.group(1)}")


def check(text: str, depth: int = 0) -> Verdict:
    """The verdict on a shell script."""
    if depth > MAX_DEPTH:
        return ask_if_sensitive(text, "nested too deeply")
    try:
        commands = parse(text)
    except ParseError as e:
        return ask_if_sensitive(text, str(e))
    shell_env: dict[str, str] = {}  # what `export` and bare assignments leave set
    verdicts = []
    for cmd in commands:
        verdicts.extend(check(s, depth + 1) for s in cmd.subs)
        verdicts.append(check_command(cmd, shell_env, text, depth))
    return worst(verdicts)


def check_command(cmd: Command, shell_env: dict[str, str], text: str, depth: int) -> Verdict:
    words, env, i = cmd.words, dict(shell_env), 0
    while i < len(words) and ASSIGNMENT.match(words[i]):
        k, v = words[i].split("=", 1)
        env[k] = v
        i += 1
    if i == len(words):
        shell_env.update(env)
        return ALLOWED
    return check_argv(words[i:], env, cmd, shell_env, text, depth)


def check_argv(
    argv: list[str],
    env: dict[str, str],
    cmd: Command,
    shell_env: dict[str, str],
    text: str,
    depth: int,
) -> Verdict:
    prog = argv[0]
    if "$" in prog or "`" in prog:
        return ask_if_sensitive(" ".join(argv), "the program is a variable")
    name = os.path.basename(prog)
    args = argv[1:]
    if name in KEYWORDS:
        return check_argv(args, env, cmd, shell_env, text, depth) if args else ALLOWED
    if name in ("export", "declare", "typeset", "local", "readonly"):
        for a in args:
            if ASSIGNMENT.match(a):
                k, v = a.split("=", 1)
                shell_env[k] = v
        return ALLOWED
    if name == "eval":
        return check(" ".join(args), depth + 1)
    if name == "env":
        return check_env(args, env, cmd, shell_env, text, depth)
    if name in SHELLS:
        return check_shell(args, cmd, text, depth)
    if name in WRAPPERS or (name == "uv" and args[:1] == ["run"]):
        return check_wrapper(args, env, cmd, shell_env, text, depth)
    rule = RULES.get(name)
    return rule(args, env) if rule is not None else ALLOWED


def runs_something(word: str) -> bool:
    name = os.path.basename(word)
    return name in RULES or name in SHELLS or name in WRAPPERS or name in ("env", "eval")


def check_wrapper(
    args: list[str],
    env: dict[str, str],
    cmd: Command,
    shell_env: dict[str, str],
    text: str,
    depth: int,
) -> Verdict:
    """`sudo -u x git ...`, `xargs -n1 git ...`, `uv run git ...`: the first argument
    that names a program the guard knows is where the wrapped command starts. A single
    argument holding a whole command line (`watch 'kubectl ...'`) is checked as one."""
    verdicts = [check(a, depth + 1) for a in args if " " in a and SENSITIVE.search(a)]
    for j, a in enumerate(args):
        if runs_something(a):
            verdicts.append(check_argv(args[j:], env, cmd, shell_env, text, depth))
            break
    return worst(verdicts)


def check_env(
    args: list[str],
    env: dict[str, str],
    cmd: Command,
    shell_env: dict[str, str],
    text: str,
    depth: int,
) -> Verdict:
    env, i = dict(env), 0
    while i < len(args):
        a = args[i]
        if a in ("-u", "--unset", "-C", "--chdir"):
            i += 2
        elif a in ("-S", "--split-string") and i + 1 < len(args):
            return check(" ".join(args[i + 1 :]), depth + 1)
        elif a.startswith("--split-string="):
            return check(a.split("=", 1)[1] + " " + " ".join(args[i + 1 :]), depth + 1)
        elif a.startswith("-"):
            i += 1
        elif ASSIGNMENT.match(a):
            k, v = a.split("=", 1)
            env[k] = v
            i += 1
        else:
            return check_argv(args[i:], env, cmd, shell_env, text, depth)
    return ALLOWED


def check_shell(args: list[str], cmd: Command, text: str, depth: int) -> Verdict:
    """`bash -c '...'` checks the script; `bash <<EOF` checks the here-document; a
    shell reading stdin from a pipe can't be followed."""
    has_c, i = False, 0
    while i < len(args):
        a = args[i]
        if a == "--":
            i += 1
            break
        if a in ("-o", "+o", "-O", "+O"):
            i += 2
            continue
        if a.startswith("-") and not a.startswith("--") and "c" in a[1:]:
            has_c = True
        if not a.startswith(("-", "+")):
            break
        i += 1
    if has_c:
        return check(args[i], depth + 1) if i < len(args) else ALLOWED
    if i < len(args):
        return ALLOWED  # a script file: what it runs is out of sight
    if cmd.stdin_scripts:
        return worst([check(s, depth + 1) for s in cmd.stdin_scripts])
    return ask_if_sensitive(text, "a shell reads commands from a pipe")


# ---------------------------------------------------------------------------
# The hook.
# ---------------------------------------------------------------------------

BLOCKED = (
    "blocked by .claude/hooks/guard.py ({rule}): {reason}. "
    "If it has to happen, stop and ask the maintainer to do it."
)


def main(stdin=None, stdout=None, stderr=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    try:
        data = json.load(stdin)
        if data.get("tool_name") != "Bash":
            return 0
        command = data["tool_input"]["command"]
        if not isinstance(command, str):
            raise TypeError(f"tool_input.command is {type(command).__name__}")
        verdict = check(command)
    except Exception as e:  # fail closed: a guard that can't decide blocks
        print(
            f"blocked by .claude/hooks/guard.py: the guard failed ({e!r}), so the command "
            "is blocked. Tell the maintainer.",
            file=stderr,
        )
        return 2
    if verdict.level == BLOCK:
        print(BLOCKED.format(rule=verdict.rule, reason=verdict.reason), file=stderr)
        return 2
    if verdict.level == ASK:
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": (
                    f".claude/hooks/guard.py ({verdict.rule}): {verdict.reason}"
                ),
            }
        }
        json.dump(out, stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
