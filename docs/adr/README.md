# Decision records

An ADR (architecture decision record) writes down one decision, why it was
made and what follows from it, so the issues that depend on it stop deciding
it again, each a little differently.

## When to write one

Write an ADR when **more than one issue depends on the same decision**: who
writes the data volume, which ports the LAN can reach, how the images are cut.
A decision that only one issue needs stays in that issue (its Approach or
Open questions).

Signs it is time:

- two specs recommend different answers to the same question;
- a spec's Open questions say "decide in #…" or "record it somewhere";
- a requirement in one issue breaks a requirement in another.

## How

- One file per record: `NNNN-short-name.md`, numbered in order, never reused.
- Sections: **Status**, **Context**, **Decision** (one heading per point, each
  naming the issues it settles), **Consequences**, and what it means for the
  issue that asked for it.
- Status is *Accepted* or *Superseded by NNNN*. A record is not edited to say
  something new: a new record replaces it, and the old one points to it.
- Every issue a record settles links back to it, and its body agrees with it.
  Where a test can back a decision, the record names the test.
- Plain and short, like the rest of the docs (see `../ISSUE_FORMAT.md`).

## Records

| ADR | Decision |
|---|---|
| [0001](0001-data-and-network.md) | Who writes `/data`, how readers open it, what the LAN can reach, where secrets live, one image or two, how data gets to Postgres. |
| [0002](0002-outing-archive.md) | The outing archive: the `outings` release of this repository, a directory as its working copy, tests fetching outings by id. |
| [0003](0003-ui-stack.md) | The UI: a React single-page app built to static files, served with a read-only data API by the pit wall pod, which proxies the engineer; Streamlit retired; dashboards; the GT7 decoder owned. Amends 0001 point 5. |
