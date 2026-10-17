# 0001: Data volume and network

**Status:** Accepted, 2026-10-17. Asked for by #194.

## Context

The engineer, the pit wall and the command-line tools share one data volume
(PVC `those-who-run-data`, `local-path`, `ReadWriteOnce`, mounted at `/data`
on the NUC). It holds `index.sqlite`, `sessions/<id>/` (Parquet laps and
`summary.json`) and `recordings/`. The pit wall runs in its own pod (#35) on
the same node, because the PV is pinned there. Both pods run as uid 1000 from
one image.

Eight open specs each decided a piece of how these share the volume and the
network, and some pieces conflicted: #35 mounts the volume read-only while
#147 puts the index in WAL mode; #135 and #140 put tokens on the volume the
pit wall mounts; #142 puts port 9850, which #136 gives write endpoints, on
the LAN. This record decides all six points at once.

Measured for this record (Python's `sqlite3`, SQLite 3.51, 2026-10-17; pinned
by `tests/test_pitwall_wal.py`):

- After the writer of a WAL database closes cleanly, only `index.sqlite` is
  left; the `-wal` and `-shm` files are gone.
- A `mode=ro` reader in a **writable** directory then opens it: it creates
  `-shm` and `-wal` itself and leaves them behind.
- A `mode=ro` reader in a **read-only** directory fails ("attempt to write a
  readonly database"). It works only while the writer is running (the files
  exist), or with `immutable=1`, which promises SQLite the file never
  changes and so returns stale or broken reads while the engineer writes.
- With WAL, a reader holding a read transaction does not block the writer's
  commit (the rollback journal it replaces does: #147).

The live cluster on 2026-10-17: the engineer (`muldoon/those-who-run:0.4.0`)
uses `hostPort` 33740/UDP and 9850/TCP, so 9850 is already on the LAN; there
is one Secret (`those-who-run-discord`), one Service (ClusterIP 9850), no
Ingress and no NetworkPolicy.

## Decision

### 1. One writer: the engineer

While the engineer runs, it is the only process that writes under
`GT7_DATA_DIR`.

- The engineer holds an exclusive `flock` on `GT7_DATA_DIR/engineer.lock` for
  as long as `run` is up. `flock` works across pods here because they share
  the node's kernel and the `local-path` directory.
- Every command that writes under the data directory (`tracks backfill`, the
  prune, the digest, the Postgres export, `jobs run`) tries the same lock
  without waiting. If the engineer holds it, the command refuses with a
  message saying to use the pit wall or let the engineer's job runner do it.
  With the engineer stopped, the command takes the lock and runs.
- Scheduled and after-session work runs inside the engineer on the job runner
  (#189). No CronJob or second pod mounts the volume to write.
- The pit wall never writes, and never takes the lock. Changes it asks for go
  through the engineer's control API (#136).

Why: the store writes from the event loop, and a second writer either makes
it wait (a lost lap row, #147) or races it (`summary.json`, #147). A lock
file is the smallest guard that works for a CLI on a laptop and a pod on the
NUC alike.

Settles: #147 R3 (the lock is this one), #189 (in-process, CLI for manual
runs), #36 R4 and #106 (job runner, not a CronJob), #133 (export job).

### 2. Readers: a writable mount, `mode=ro` in SQLite

- The pit wall mounts the PVC at `/data` **read-write**, and mounts its
  `sessions` subdirectory a second time at `/data/sessions` with
  `readOnly: true`.
- It opens the index with `mode=ro` (as `pitwall/data.py` `open_index` does
  today), never `immutable`, and never creates it. It opens a connection per
  query and closes it, so it never holds a read transaction for long.
- Any other reader (a CLI that only reads) does the same.

Why: a read-only mount of `/data` cannot open the WAL index while the engineer
is stopped (Context), and the pit wall is most useful exactly then, after a
race. `immutable` gives wrong answers while the engineer writes. Having the
engineer hold a connection open only helps while it runs. The `sessions`
read-only mount keeps the lap files and summaries safe at the mount, so the
only things the pit wall could write are in the volume's root: the index's
side files, which SQLite itself needs.

Consequences: the pit wall leaves `index.sqlite-wal` and `-shm` behind when it
reads with the engineer stopped; that is normal, and the engineer recovers
them at start. The guard against the pit wall writing the index is the code
(`mode=ro`, `tests/test_pitwall.py::test_reads_only`), not the mount.

Settles: #35 R2 and AC3, #147 R4 (the cache stamp must also follow
`index.sqlite-wal`, since the main file's mtime only changes at checkpoint)
and R5, #141.

### 3. Network: what the LAN can reach

The engineer moves to the host network (#142), and Kubernetes leaves
NetworkPolicy for host-network pods undefined, so every port the engineer
listens on is treated as open to the LAN. The guard is the port and the
token, not a policy.

| Port | Serves | Who reaches it | Token |
|---|---|---|---|
| 33740/udp | GT7 telemetry from the PS5 | LAN | none (GT7's protocol) |
| 9850/tcp | `/metrics`, `/healthz`, read-only `GET /api/v1/status` | LAN, Prometheus, the pit wall | none: read-only, never a secret |
| 9851/tcp (`GT7_CONTROL_PORT`) | the control API: everything that changes the engineer (`/api/v1/discover`, `/api/v1/config`, re-running jobs) | the pit wall, through the Service | admin token on **every** request |
| 80 (Traefik) → 8501 | the pit wall, `pitwall.nuc.home.arpa` | LAN | none to look; setup pages ask for the admin token |

- Nothing that writes or changes state is served on 9850.
- 9851 serves nothing without the token, reads included, so a mistake in
  route registration fails closed.
- The pit wall has no `hostPort` and no host network: only the Ingress
  reaches it. It is LAN-only with no login (the roadmap's open decision).
- The pit wall pod never holds the admin token. The driver types it into the
  setup page (#140 R3) and the pit wall passes it on to 9851.

Why: one port per trust level is easy to check (`curl` on the LAN) and does
not depend on how the CNI treats host-network pods.

Settles: #142 (R2 also checks 9851 is free), #136 R4 (writes on 9851), #140
R1, #35 R5.

### 4. Secrets: never on the data volume

- The Discord token stays in the Kubernetes Secret `those-who-run-discord`,
  later fed from Vault by External Secrets (#25). The admin token
  (`GT7_ADMIN_TOKEN`) and the Postgres DSN (`GT7_PG_DSN`) go the same way,
  in Secrets only the engineer's pod references.
- A secret the engineer has to write itself (a Discord token entered during
  first-run setup, #135; the admin token generated when none is set, #140 R2)
  goes in `GT7_SECRETS_DIR`, never under `GT7_DATA_DIR`. On the NUC that is
  `/secrets`, a second small PVC (`those-who-run-secrets`) mounted only by the
  engineer. Off the NUC it defaults to `~/.config/those-who-run`.
- The engineer refuses to start if `GT7_SECRETS_DIR` is inside
  `GT7_DATA_DIR`. If the directory can't be written, the secret is kept in
  memory and the log says it won't survive a restart.
- `/data/settings.json` (#135) holds only settings that aren't secret: the PS5
  address, Discord guild and channel ids. The pit wall may read it.
- Order of precedence stays #135's and #191's: the environment wins.

Why: both pods run as uid 1000, so a 0600 file on the shared volume is
readable by the pit wall process. A separate volume is the only thing that
keeps a token out of the pit wall pod without giving the pods different
users, which would break the pit wall's `-shm` file (point 2).

Settles: #135 R2 and R4, #140 R2, #25, #35 R3.

### 5. Images: two targets from one Dockerfile

- The Dockerfile gets two final stages:
  - `engineer`: no `web` extra; the Piper voice and the audio libraries.
    Published as `muldoon/those-who-run:<version>`.
  - `pitwall`: the `web` extra (Streamlit, pandas, pyarrow); no voice, no
    audio libraries, a health check on `/_stcore/health`. Published as
    `muldoon/those-who-run:<version>-pitwall`.
- Both are built and pushed by the same release job, with the same version,
  and the manifests bump both tags together, so the pit wall always reads the
  schema the engineer writes.
- #26's 450 MB budget is for the `engineer` image.
- Until #26 lands (0.8), the single image keeps the `web` extra and runs both.

Why: the engineer never imports Streamlit, pandas or pyarrow (about 300 MB),
and every release pulls it onto the NUC. One Dockerfile and one version keep
the two from drifting apart; a tag suffix keeps one Docker Hub repository.

Settles: #26 (its Open question), #35 (image tag), #162.

### 6. Postgres: an export job, never on the lap path

- The push to the home-lab Postgres is a job on the engineer's job runner
  (#189). It reads lap rows that have no `exported_at` yet (from the lap
  summary table, #115), inserts them idempotently on `(session_id, lap)`, and
  sets `exported_at`. The engineer writes that mark, so point 1 holds.
- The lap writer and `end_session` never touch Postgres. A slow or
  unreachable Postgres delays the export, not a lap or a card.
- The backfill for stored sessions is the same job: every row with no
  `exported_at`.

Settles: #133 R2, R3 and R4, #189.

## What #35 does because of this

- **Image:** the engineer's tag with `args: ["web"]` now; the
  `<version>-pitwall` tag once #26 splits the image. Bump both Deployments
  together.
- **Volumes** (replaces R2): the PVC at `/data` with no `readOnly`, and the
  same PVC again with `subPath: sessions` at `/data/sessions`,
  `readOnly: true`. Same `fsGroup: 1000` as the engineer.
- **No secrets:** no `envFrom` of `those-who-run-discord`, no
  `GT7_ADMIN_TOKEN`, no `/secrets` volume. Only the ConfigMap
  (`GT7_DATA_DIR`, `GT7_WEB_PORT`, `HOME=/tmp`).
- **Network:** no `hostPort`, no `hostNetwork`; a ClusterIP Service on 8501
  and the Traefik Ingress.
- **AC3** becomes: `touch /data/sessions/x` in the pit wall pod fails with a
  read-only error, and `kubectl get pod -o yaml` shows no Secret referenced.
- **New check:** with the engineer scaled to 0, the pit wall still lists the
  sessions. Once #147 has put the index in WAL mode, this is the case a
  read-only mount would fail.
- `RollingUpdate` is fine for the pit wall: it takes no lock and holds no
  write.

## Consequences

- The issues above link here, and their bodies follow this record.
- A new tool that writes under `/data` takes the writer lock (point 1); a new
  port the engineer opens gets a row in point 3's table; a new secret goes in
  a Secret or `GT7_SECRETS_DIR` (point 4). Changing any of these needs a new
  ADR that supersedes this one.
- `tests/test_pitwall_wal.py` pins point 2: the pit wall's data layer opens a
  WAL index after the engineer's store has closed, with `sessions/` read-only,
  and a fully read-only directory cannot.

## References

- SQLite, "Write-Ahead Logging", read-only databases:
  https://www.sqlite.org/wal.html
- Kubernetes, Network Policies (host-network pods):
  https://kubernetes.io/docs/concepts/services-networking/network-policies/
- Kubernetes, volumes with `subPath`:
  https://kubernetes.io/docs/concepts/storage/volumes/#using-subpath
