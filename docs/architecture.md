# Architecture

For anyone, person or agent, new to the code: the shape of the system in three
pictures, before the detail in the guides. Back to the [docs index](README.md).

## The engineer

```mermaid
flowchart LR
  subgraph ps5["PS5"]
    gt7["GT7"]
    psdiscord["Discord on the PS5"]
  end
  headset(["headset"])

  subgraph engineer["engineer: those-who-run run"]
    telemetry["telemetry<br/>(gt-telem, heartbeat)"]
    state["state<br/>RaceState frames"]
    rules["rules<br/>pure functions"]
    queue["speech queue<br/>max_age_seconds"]
    piper["Piper<br/>+ sentence cache"]
    player["voice player<br/>discord.py"]
    results["results poster"]
    writer["store writer"]
    recorder["recorder"]
    http["/metrics, /healthz,<br/>/api/v1/status"]
  end

  subgraph discord["Discord"]
    voice["voice channel"]
    text["results text channel"]
  end

  store[("GT7_DATA_DIR<br/>the store")]
  recs[("GT7_RECORD_DIR<br/>outing recordings")]
  prom(["Prometheus, probes"])

  gt7 -- "UDP 33740, 60 Hz" --> telemetry
  telemetry -- "heartbeat, UDP 33739" --> gt7
  telemetry --> state --> rules --> queue --> piper --> player
  player -- "Opus audio" --> voice
  voice --> psdiscord --> headset
  state --> results -- "DISCORD_RESULTS_CHANNEL_ID" --> text
  state --> writer --> store
  state --> recorder --> recs
  prom -- "GT7_METRICS_PORT 9850" --> http
```

The PS5 streams telemetry to whoever sends it a heartbeat. The engineer turns
each packet into a `RaceState` frame; the rules, which have no I/O, turn
consecutive frames into callouts; the queue drops what is too old to say;
Piper speaks each sentence once and caches it; and discord.py plays the result
into the voice channel the PS5 has joined. Beside the voice, the same frames
feed the results card, the store and the outing recordings, and the read-only
port reports health and metrics. The detail is in
[the engineer guide](engineer.md#how-it-works),
[configuration](setup.md#configuration) and
[metrics](operations.md#metrics); the ports are settled in
[ADR 0001](adr/0001-data-and-network.md).

## The store and the pit wall

```mermaid
flowchart LR
  subgraph eng["engineer"]
    run["those-who-run run<br/>holds engineer.lock"]
    ro["read-only port<br/>GT7_METRICS_PORT 9850<br/>/api/v1/status, /api/v1/dash"]
    ctl["control port<br/>GT7_CONTROL_PORT 9851<br/>(unset: off)"]
  end

  subgraph data["GT7_DATA_DIR, one volume"]
    lock["engineer.lock"]
    index[("index.sqlite<br/>WAL mode")]
    laps[("sessions/#lt;id#gt;/<br/>lap-NN.parquet, summary.json")]
  end

  subgraph pw["pit wall: those-who-run pitwall, GT7_PITWALL_PORT 9852"]
    api["data API<br/>/api/v1/sessions…<br/>read-only, mode=ro"]
    proxy["engine proxy<br/>/api/engine/*"]
    static["web app<br/>GT7_PITWALL_STATIC"]
  end

  browser(["browser: one origin"])

  run -- "the one writer" --> lock
  run --> index
  run --> laps
  index -. "reads" .-> api
  laps -. "reads" .-> api
  proxy -- "/api/engine/status → /api/v1/status<br/>/api/engine/dash → /api/v1/dash<br/>GT7_ENGINEER_URL" --> ro
  proxy -- "/api/engine/control/* → /api/v1/*<br/>GT7_ENGINEER_CONTROL_URL" --> ctl
  browser --> static
  browser --> api
  browser --> proxy
```

The engineer is the store's only writer: `run` holds `engineer.lock` while it
is up, writes each lap's frames to Parquet and then its row to
`index.sqlite`. The pit wall only reads, opening the index `mode=ro` per
request (WAL mode keeps it from holding up the writer). It serves the React
app as static files and proxies the engineer's ports, so the browser talks to
one origin and never to the engineer directly. The detail is in
[the pit wall guide](pitwall.md) ([the data API](pitwall.md#the-data-api),
[the store](pitwall.md#the-store)) and in [ADR 0001](adr/0001-data-and-network.md)
and [ADR 0003](adr/0003-ui-stack.md).

## A release

```mermaid
flowchart TD
  pr["a PR merged to main<br/>feat:, fix:, perf:, deps:"]
  rpr["release-please keeps one PR open<br/>chore(release): x.y.z<br/>CHANGELOG.md, version strings"]
  merge["the release PR merged"]
  tag["tag vx.y.z<br/>and the GitHub release"]
  subgraph rel["release.yml"]
    check["the tag has a release<br/>tag = v + __version__<br/>make check"]
    build["build both images"]
    smoke["smoke runs<br/>--version, smoke-pitwall.sh"]
    push["push to Docker Hub<br/>muldoon/those-who-run:x.y.z (and latest)<br/>muldoon/those-who-run:x.y.z-pitwall"]
  end
  deploy["the operator's deployment<br/>pulls both tags: up to the operator"]

  pr --> rpr --> merge --> tag --> check --> build --> smoke --> push --> deploy
```

Merged PRs collect in one release PR, and merging it ships. release-please
tags the merge commit and calls `release.yml`, which runs `make check` on the
tagged commit, builds the engineer's image and the pit wall's, smoke-tests
both, and pushes the two tags. Where and how they run is up to whoever runs
them: [Deploying](operations.md#deploying) says what the two images need (one
data volume, one engineer at a time, and waiting for `/healthz` to say `idle`
before replacing the engineer). The detail is in
[Releasing](operations.md#releasing).
