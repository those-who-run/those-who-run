# Those Who Run 走り屋

**A self-hosted voice race engineer for Gran Turismo 7.**

<!-- x-release-please-start-version -->
Current release: v0.7.4
<!-- x-release-please-end -->

Picture a two-bay tuning shop on the industrial edge of Tsukuba in 1995. A
Hachi-Roku on the lift, a Sylvia outside with the bonnet off, a wall of
dog-eared timing sheets, a stopwatch on a lanyard and a radio that only ever
says what matters. Nobody there has a subscription to anything. The engineer
on the pit wall counts your laps, watches your fuel and tells you where you
stand, in your ear, in plain words.

That is this. It reads the PS5's UDP telemetry, applies deterministic rules,
synthesises speech locally with Piper, and plays it into a Discord voice
channel. Join that channel from the PS5's Discord integration and the engineer
speaks inside your PSVR2 headset while the HUD is gone.

No subscription, and no cloud service of its own: the telemetry, the rules and
the speech stay on one small box on your LAN. The voice itself reaches you
through Discord, so it needs a Discord server and a bot.

## Screenshots

<!-- The pit wall on a phone and a desktop: #336 fills this in. -->
The pit wall, the web app over every session you have driven, is described in
[the pit wall guide](docs/pitwall.md).

## How it works

```
PS5 (GT7) --UDP 33740--> engineer --Piper WAV--> Discord voice channel --> PS5 Discord --> headset
         <--UDP 33739 heartbeat--
```

The engineer turns telemetry into short spoken calls (lap times, fuel, the
final lap, places gained and lost) and keeps every lap in a store on disk. The
pit wall, a second image, reads that store and shows it in a browser. The
details are in [the engineer guide](docs/engineer.md#how-it-works).

## Quick start

You need:

- A PS5 running GT7 with **Settings > Network > Telemetry** enabled, on the same
  LAN as the host, with a fixed address.
- A Discord server with a voice channel, and a bot application with the
  **Connect** and **Speak** permissions in that channel. No privileged intents.
- The PS5 signed in to Discord and joined to the same voice channel.
- A Linux host that runs containers (amd64).

Then run the engineer:

```sh
podman run --rm \
  -e GT7_PS5_IP=<ps5-address> \
  -e DISCORD_BOT_TOKEN=... \
  -e DISCORD_VOICE_CHANNEL_ID=... \
  -p 33740:33740/udp -p 9850:9850 \
  -v ./data:/data \
  muldoon/those-who-run:0.7.4  # x-release-please-version
```

Check the voice path with `those-who-run say "Radio check"`, then drive. Next:

- every setting and command: [setup](docs/setup.md);
- what it says and how to change it: [the engineer](docs/engineer.md);
- the pit wall on your phone: [the pit wall](docs/pitwall.md);
- running both images for good: [operations](docs/operations.md#deploying).

## Guides

All the docs are listed in the [docs index](docs/README.md).

| Guide | For |
|---|---|
| [Setup](docs/setup.md) | requirements, configuration, running, every command |
| [The engineer](docs/engineer.md) | what it says, rules, track and session detection, results, sessions |
| [The pit wall](docs/pitwall.md) | the web app, the data API, the store, the pitwall image |
| [Operations](docs/operations.md) | deploying, metrics and health, releasing, Dependabot |
| [Telemetry](docs/telemetry.md) | what GT7 reports, recordings, the archive, known limits |
| [Development](docs/development.md) | `make` targets, fixtures, the web app, the brand |

## Known limits

- GT7 only exposes your own car. There are no gaps to the cars around you.
- Only the Discord send path is implemented. Spoken questions are a later phase.

The rest are in [the telemetry guide](docs/telemetry.md#known-limits).

## Roadmap

[ROADMAP.md](ROADMAP.md) has the direction: principles, the streams that
run in parallel, their order and the open decisions. Details live in the
GitHub milestones and issues, each issue labelled with its stream:
https://github.com/those-who-run/those-who-run/milestones

## Licence

GPL-3.0-only. gt-telem and Piper are GPL-3.0, which this project inherits.
The car table comes from ddm999/gt7info under MIT-0, and the track table from
gt-telem and Bornhall/gt7telemetry.
走り屋 is used here in its plain sense, people who run, and claims nothing else.
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) lists the third-party data,
voice and fonts, with their licences and attribution.

## Disclaimer

Those Who Run is an independent project. It is not affiliated with, endorsed
by or sponsored by Sony Interactive Entertainment, Polyphony Digital or Discord.
Gran Turismo is a trademark of Sony Interactive Entertainment; PlayStation and
PS5 are trademarks of Sony Interactive Entertainment; Discord is a trademark of
Discord Inc. "Advan" is a Yokohama Rubber brand name, used descriptively. Other
names belong to their owners.
