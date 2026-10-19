# Docs

Everything about Those Who Run past the [front page](../README.md), one guide
per reader. Each guide opens with who it is for.

## Guides

- [Architecture](architecture.md): the engineer, the store and the pit wall, and a release, in three diagrams. Start here.
- [Setup](setup.md): requirements, the configuration table, running from the image or from source, the audio check, and the commands table.
- [The engineer](engineer.md): what it says and the script, the rules and their settings, session kind, track detection, cars, the results channel, and sessions.
- [The pit wall](pitwall.md): the web app as a driver uses it, the data API, the store, the preview on a phone or iPad, and the pitwall image.
- [Operations](operations.md): deploying the two images, metrics, `/healthz` and `/api/v1/status`, releasing, and Dependabot.
- [Telemetry](telemetry.md): what GT7 actually reports, recordings and the archive, and the known limits.
- [Development](development.md): `make check` and the make table, fixtures, the web app, and the brand and wordmark.
- [The web app](../web/README.md): building and checking the React pit wall in `web/`.

## Reference

- [Design guide](design.md): the web app's tokens, type, layout and states.
- [Issue format](ISSUE_FORMAT.md): what goes in each section of an issue.
- [Decision records](adr/README.md): the ADRs, and when to write one.
  - [0001](adr/0001-data-and-network.md): data and network.
  - [0002](adr/0002-outing-archive.md): the outing archive.
  - [0003](adr/0003-ui-stack.md): the UI stack.
  - [0004](adr/0004-design-language.md): the design language.
- [Roadmap](../ROADMAP.md) and [changelog](../CHANGELOG.md).
