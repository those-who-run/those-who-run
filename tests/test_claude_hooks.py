"""The commit hooks and Claude Code's guard (#339, #352).

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


@pytest.fixture(autouse=True)
def guard_log(tmp_path, monkeypatch):
    """The guard's log, kept out of ~/.claude."""
    path = tmp_path / "twr-guard.log"
    monkeypatch.setenv("TWR_GUARD_LOG", str(path))
    return path


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
        'gh pr edit 1 --title "feat: x" --body "$(cat <<\'EOF\'\n'
        "Don't pass git commit --no-verify; it's blocked (see #339).\nEOF\n)\"",
    ],
)
def test_text_that_mentions_the_flags_is_allowed(command):
    assert decision(command) == "allow"


# #352: outward-facing actions. (blocked, near miss) again.
OUTWARD = [
    # git push: forced, mirrored, deleting, tags, main
    ("git push --force origin feat/x", "git push origin feat/x"),
    ("git push -f origin feat/x", "git push -u origin feat/x"),
    ("git push -uf origin feat/x", "git push -o ci.skip origin feat/x"),
    ("git push --force-with-lease origin feat/x", "git push --set-upstream origin feat/x"),
    ("git push --mirror origin", "git push --dry-run origin feat/x"),
    ("git push --delete origin feat/x", "git push origin feat/x:feat/x"),
    ("git push origin :feat/x", "git push origin HEAD:feat/x"),
    ("git push origin +feat/x", "git push origin feat/x"),
    ("git push --tags", "git push"),
    ("git push --follow-tags origin feat/x", "git push origin feat/x"),
    ("git push origin v0.7.5", "git push origin fix/v-shaped-trace"),
    ("git push origin refs/tags/v0.7.5", "git push origin refs/heads/feat/x"),
    ("git push origin tag v0.7.5", "git push origin feat/tagging"),
    ("git push origin main", "git push origin feat/main-menu"),
    ("git push origin HEAD:main", "git push origin HEAD:feat/x"),
    ("git -C . push -f origin main", "git -C . push origin feat/x"),
    ('git commit -m "x" && git push -f', 'git commit -m "never git push --force"'),
    # git tag: creating a v* tag
    ("git tag v0.7.5", "git tag -l 'v*'"),
    ('git tag -a v0.7.5 -m "0.7.5"', "git tag -d v0.7.5"),
    ("git tag -s v0.7.5 HEAD", "git tag scratch-before-rebase"),
    # gh: merging past the checks, releases, workflows, settings
    ("gh pr merge 1 --admin", "gh pr merge 1 --squash"),
    ("gh release create v0.7.5", "gh release view v0.7.4"),
    ("gh release edit v0.7.4 --draft", "gh release list"),
    ("gh release delete v0.7.3", "gh release download outings -R those-who-run/outings"),
    ("bash -c 'gh release delete v0.7.3'", "bash -c 'gh release list'"),
    ("gh release upload v0.7.4 x.tgz", "gh release view outings"),
    ("gh workflow run release.yml", "gh workflow list"),
    ("gh workflow disable ci.yml", "gh workflow view ci.yml"),
    ("gh repo edit --visibility private", "gh repo view"),
    ("gh repo delete those-who-run/those-who-run --yes", "gh repo view --json name"),
    ("gh repo rename x", "gh repo clone those-who-run/outings"),
    ("gh repo archive", "gh repo view --web"),
    ("gh secret set DOCKERHUB_TOKEN", "gh secret list"),
    ("gh variable set X --body y", "gh variable list"),
    ("gh ruleset create", "gh ruleset list"),
    ("gh alias set m 'pr merge --admin'", "gh alias list"),
    ("gh auth token", "gh auth status"),
    # gh api: writes to the repository's settings, refs and releases
    ("gh api -X PUT repos/{owner}/{repo}/rulesets/1", "gh api repos/{owner}/{repo}/rulesets"),
    ("gh api --method PATCH repos/{owner}/{repo}", "gh api repos/{owner}/{repo}"),
    ("gh api repos/{owner}/{repo} -f visibility=private", "gh api repos/{owner}/{repo} -q .name"),
    (
        "gh api -XPUT repos/those-who-run/those-who-run/actions/permissions -F enabled=false",
        "gh api -X GET repos/those-who-run/those-who-run/actions/permissions -f per_page=1",
    ),
    (
        "gh api -X DELETE repos/{owner}/{repo}/environments/release",
        "gh api repos/{owner}/{repo}/environments",
    ),
    (
        "gh api -X PUT repos/{owner}/{repo}/collaborators/x",
        "gh api repos/{owner}/{repo}/collaborators",
    ),
    ("gh api -X POST repos/{owner}/{repo}/hooks -f url=x", "gh api repos/{owner}/{repo}/hooks"),
    ("gh api -X POST repos/{owner}/{repo}/keys -f key=x", "gh api repos/{owner}/{repo}/keys"),
    (
        "gh api -X DELETE repos/{owner}/{repo}/branches/main/protection",
        "gh api repos/{owner}/{repo}/branches/main/protection",
    ),
    (
        "gh api repos/{owner}/{repo}/git/refs -f ref=refs/tags/v1 -f sha=x",
        "gh api repos/{owner}/{repo}/git/refs",
    ),
    ("gh api -X PUT repos/{owner}/{repo}/pulls/1/merge", "gh api repos/{owner}/{repo}/pulls/1"),
    (
        "gh api graphql -f query='mutation { mergePullRequest(input: {}) { clientMutationId } }'",
        "gh api graphql -f query='mutation { updateProjectV2ItemFieldValue(input: {}) { x } }'",
    ),
    # docker and podman: registries, privileged containers, host mounts
    ("docker push muldoon/those-who-run:0.7.5", "docker pull python:3.14"),
    ("docker login -u muldoon", "docker ps"),
    ("podman login docker.io", "podman images"),
    ("podman logout docker.io", "podman build --format docker -t x ."),
    ("docker image push x", "docker image ls"),
    ("docker buildx build --push .", "docker buildx build --load ."),
    ("podman push muldoon/those-who-run:ci", "podman run --rm muldoon/those-who-run:ci --version"),
    ("docker run --privileged alpine", "docker run --rm alpine"),
    ("docker run -v /:/host alpine", "docker run -v ./data:/data alpine"),
    ("podman run -v ~/.kube:/k alpine", "podman run -v ./voices:/voices alpine"),
    ("docker run -v $HOME:/h alpine", "docker run -v $HOME/Projects/x/data:/data alpine"),
    ("docker run -v ~/.ssh:/s:ro alpine", "docker run -v /tmp/x:/x alpine"),
    (
        "docker run --mount type=bind,source=/,target=/h alpine",
        "docker run --mount type=volume,target=/d alpine",
    ),
    ("docker run -v /var/run/docker.sock:/var/run/docker.sock x", "docker run -p 9852:9852 x"),
    # kubectl and helm: anything that writes to the cluster
    ("kubectl apply -f x.yaml", "kubectl get pods"),
    ("kubectl --context nuc delete pod x", "kubectl --context nuc get pod x"),
    (
        "kubectl --kubeconfig ~/.kube/nuc.config delete pod x",
        "kubectl --kubeconfig ~/.kube/nuc.config get pods",
    ),
    ("kubectl -n those-who-run exec deploy/x -- ls", "kubectl -n those-who-run logs deploy/x"),
    ("kubectl edit deploy/x", "kubectl describe deploy/x"),
    ("kubectl patch deploy/x -p '{}'", "kubectl get deploy/x -o yaml"),
    ("kubectl scale deploy/x --replicas=0", "kubectl top pods"),
    ("kubectl rollout restart deploy/x", "kubectl rollout status deploy/x"),
    ("kubectl rollout undo deploy/x", "kubectl rollout history deploy/x"),
    ("kubectl set image deploy/x x=y", "kubectl explain deploy"),
    ("kubectl label pod x a=b", "kubectl get pods --show-labels"),
    ("kubectl annotate pod x a=b", "kubectl events"),
    ("kubectl drain node1", "kubectl get nodes"),
    ("kubectl cordon node1", "kubectl auth can-i get pods"),
    ("kubectl port-forward svc/x 9852", "kubectl get svc"),
    ("kubectl cp x pod:/tmp/x", "kubectl api-resources"),
    ("kubectl replace -f x.yaml", "kubectl diff -f x.yaml"),
    ("kubectl create ns x", "kubectl version"),
    ("kubectl config use-context nuc", "kubectl config current-context"),
    ("kubectl config set-context --current --namespace=x", "kubectl config get-contexts"),
    ("oc delete pod x", "oc get pods"),
    ("helm install x chart", "helm list -A"),
    ("helm upgrade x chart", "helm template x chart"),
    ("helm uninstall x", "helm status x"),
    ("helm rollback x 1", "helm history x"),
    ("helm registry login ghcr.io", "helm show values chart"),
    # the same, wrapped
    ("watch -n 5 'kubectl delete pod x'", "watch -n 5 'kubectl get pods'"),
    ("env KUBECONFIG=/x kubectl delete pod x", "env KUBECONFIG=/x kubectl get pods"),
    ('echo "$(gh release create v1)"', 'echo "$(gh release list)"'),
]


@pytest.mark.parametrize(("blocked", "near_miss"), OUTWARD)
def test_outward_facing_actions_are_blocked(blocked, near_miss):
    assert decision(blocked) == "block"
    assert decision(near_miss) == "allow"


@pytest.mark.parametrize(
    "command",
    [
        "gh issue create --title x --body y",
        "gh issue comment 1 --body hi",
        "gh issue edit 1 --add-label x",
        "gh issue close 1",
        "gh pr create --title x --body y",
        "gh pr comment 1 --body hi",
        "gh pr review 1 --approve",
        "gh pr close 1",
        "bash -c 'gh issue comment 1 --body hi'",
        "gh api repos/{owner}/{repo}/issues/1/comments -f body=hi",
        "gh api graphql -f query='mutation { addComment(input: {}) { clientMutationId } }'",
        "gh pr list -R anthropics/claude-code",
        "gh issue view 1 --repo someone/else",
        "GH_REPO=someone/else gh issue list",
        "gh run rerun 123",
    ],
)
def test_public_posts_and_other_repositories_ask(command):
    assert decision(command) == "ask"


@pytest.mark.parametrize(
    "command",
    [
        "gh issue view 1",
        "gh pr view 1 --comments",
        "gh pr checks 1",
        "gh pr list -R those-who-run/outings",
        "gh api repos/{owner}/{repo}/issues/1/comments",
        "gh run view 123 --log-failed",
    ],
)
def test_reading_github_passes(command):
    assert decision(command) == "allow"


def test_a_block_beats_an_ask():
    assert decision("gh issue comment 1 --body hi && gh pr merge 1 --admin") == "block"


def test_blocks_and_asks_are_logged(guard_log):
    decision("gh pr merge 1 --admin")
    decision("gh issue comment 1 --body hi")
    decision("gh issue view 1")
    lines = guard_log.read_text().splitlines()
    assert len(lines) == 2
    when, verdict, rule, command = lines[0].split("\t")
    assert (verdict, rule, json.loads(command)) == (
        "block",
        "gh-admin-merge",
        "gh pr merge 1 --admin",
    )
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d{4}", when)
    assert lines[1].split("\t")[1:3] == ["ask", "gh-issue-comment"]


def test_the_log_keeps_the_first_200_characters(guard_log):
    decision("gh pr merge 1 --admin " + "x" * 500)
    command = json.loads(guard_log.read_text().split("\t")[3])
    assert len(command) == 200


def test_a_command_it_cannot_parse_asks_when_it_names_git():
    assert decision("git commit -m 'unterminated") == "ask"
    assert decision("ls 'unterminated") == "allow"


@pytest.mark.parametrize(
    "command",
    [
        '$GIT commit -n -m "git"',
        '"$PY" scripts/openapi.py --check',
        "${G} status",
        "$(which git) status",
        "g=git; $g status",
        "alias g=git; g status",
        "alias ll='ls -l'; ll",
    ],
)
def test_a_program_in_a_variable_or_an_alias_asks(command):
    assert decision(command) == "ask"


@pytest.mark.parametrize(
    "command",
    [
        "g=git; $g commit --no-verify -m x",
        "export g=git; $g commit -n -m x",
        "G=/usr/bin/git; ${G} commit -n -m x",
        "alias g=git; g commit --no-verify -m x",
        "alias g='git commit'; g -n -m x",
    ],
)
def test_a_variable_or_an_alias_set_in_the_command_is_followed(command):
    assert decision(command) == "block"


def test_a_variable_or_an_alias_set_elsewhere_does_not_follow_the_program():
    assert decision("g=git; echo $g") == "allow"
    assert decision("alias g=git; echo g") == "allow"


# (blocked, near miss): writes to the common .git/hooks or to .git/config, which holds
# core.hooksPath, turn the hooks off for every worktree.
HOOKS_DIR = [
    ("rm -rf .git/hooks", "rm -rf .github/hooks-notes"),
    ("chmod -x .git/hooks/pre-commit", "chmod +x scripts/git-hook.sh"),
    ("cp scripts/git-hook.sh .git/hooks/pre-commit", "cat .git/hooks/pre-commit"),
    ("mv .git/hooks/commit-msg /tmp/x", "ls .git/hooks"),
    ("echo x > .git/hooks/pre-commit", "echo x > notes.txt"),
    ("printf '[core]\\n' >> .git/config", "grep hooksPath .git/config"),
    ("tee -a /home/u/repo/.git/config < x", "tee notes.txt < x"),
    ("sudo rm .git/hooks/commit-msg", "sudo ls .git/hooks"),
    ("bash -c 'truncate -s0 .git/hooks/pre-commit'", "bash -c 'wc -l .git/hooks/pre-commit'"),
    ('rm -rf "$(git rev-parse --git-common-dir)/hooks"', 'ls "$(git rev-parse --git-common-dir)"'),
    (
        'd=$(git rev-parse --git-path hooks); rm -rf "$d"',
        'd=$(git rev-parse --git-path hooks); ls "$d"',
    ),
    ("python3 -c \"open('.git/hooks/pre-commit', 'w')\"", "python3 -c \"print('hooks')\""),
    ("find .git/hooks -delete", "find . -name '*.py'"),
]


@pytest.mark.parametrize(("blocked", "near_miss"), HOOKS_DIR)
def test_writing_the_hooks_directory_or_git_config_is_blocked(blocked, near_miss):
    assert decision(blocked) == "block"
    assert decision(near_miss) == "allow"


def test_text_that_mentions_the_hooks_directory_is_allowed():
    assert decision('git commit -m "docs: never rm .git/hooks"') == "allow"
    assert decision("gh issue list --search 'rm -rf .git/hooks'") == "allow"
    assert decision("make hooks") == "allow"


@pytest.mark.parametrize("program", ["git push", "gh", "kubectl", "helm", "docker", "podman"])
def test_a_command_it_cannot_parse_asks_when_it_names_a_guarded_program(program):
    assert decision(f"{program} x 'unterminated") == "ask"


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


def test_settings_deny_the_secrets_and_ask_before_public_posts_and_policy_edits():
    permissions = json.loads((ROOT / ".claude" / "settings.json").read_text())["permissions"]
    secrets = [
        ".env",
        ".env.*",
        "~/.kube/**",
        "~/.ssh/**",
        "~/.docker/config.json",
        "~/.config/gh/**",
        "~/.config/containers/auth.json",
        "//run/user/*/containers/auth.json",  # ${XDG_RUNTIME_DIR}/containers/auth.json
        "~/.netrc",
    ]
    for path in secrets:
        assert f"Read({path})" in permissions["deny"]
        assert f"Edit({path})" in permissions["deny"]  # Edit covers Write and NotebookEdit
    for cmd in ("issue create", "issue comment", "issue edit", "issue close"):
        assert f"Bash(gh {cmd} *)" in permissions["ask"]
    for cmd in ("pr create", "pr comment", "pr review", "pr close"):
        assert f"Bash(gh {cmd} *)" in permissions["ask"]
    assert "Edit(**/.claude/settings.json)" in permissions["ask"]
    assert "Edit(**/.claude/hooks/**)" in permissions["ask"]
    assert permissions["disableBypassPermissionsMode"] == "disable"
    # Claude Code consults only Read and Edit rules for paths (a Write rule warns).
    assert not [r for r in permissions["deny"] + permissions["ask"] if r.startswith("Write(")]


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
