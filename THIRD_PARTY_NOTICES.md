# Third-party notices

Those Who Run is GPL-3.0-only (see [LICENSE](LICENSE)). It ships, adapts or
draws from the third-party works below, under their own licences. Packages
installed from PyPI and npm (`uv.lock`, `web/package-lock.json`) carry their
own licence files.

## The voice: Piper `en_GB-alba-medium`

The engineer's image downloads the Piper voice `en_GB-alba-medium`
(`voices/SHA256SUMS`, from
https://huggingface.co/rhasspy/piper-voices/tree/v1.0.0/en/en_GB/alba/medium).
Its model card is in
[`licenses/en_GB-alba-medium.MODEL_CARD`](licenses/en_GB-alba-medium.MODEL_CARD).

The voice is trained on the **Alba speech corpus** by Cassia
Valentini-Botinhao and Junichi Yamagishi, University of Edinburgh (2019),
https://datashare.ed.ac.uk/handle/10283/3270, licensed under the Creative
Commons Attribution 4.0 International licence (CC BY 4.0),
https://creativecommons.org/licenses/by/4.0/. The voice model was fine-tuned
from Piper's U.S. English `lessac` voice by the Piper project
(https://github.com/rhasspy/piper). Those Who Run uses the voice unchanged.

## Fonts: Barlow, Barlow Semi Condensed and Noto Sans CJK JP

All three are under the SIL Open Font License, Version 1.1. The copyright
notices and the licence text are in [`licenses/OFL-1.1.txt`](licenses/OFL-1.1.txt).

- **Barlow** and **Barlow Semi Condensed**, Copyright 2017 The Barlow Project
  Authors (https://github.com/jpt/barlow). The web app self-hosts them from
  `@fontsource/barlow` and `@fontsource/barlow-semi-condensed`, and the pit
  wall's image serves them. The docs' banners and social preview in
  `docs/assets/` carry the outlines of the tagline drawn from Barlow by
  `scripts/brand_assets.py`, beside the wordmark's.
- **Noto Sans CJK JP**, Copyright 2014-2021 Adobe (http://www.adobe.com/), with
  Reserved Font Name 'Source' (https://github.com/notofonts/noto-cjk). The
  wordmark and icons carry the outlines of 走り屋 drawn from it (and of "Those
  Who Run" from Barlow Semi Condensed) by `scripts/wordmark.py`; no font file
  is shipped.

## Data tables

- **Tracks**, `src/those_who_run/data/tracks.csv`: adapted from gt-telem
  (https://github.com/RaceCrewAI/gt-telem, GPL-3.0), which adapted it from
  Bornhall/gt7telemetry (https://github.com/Bornhall/gt7telemetry, GPL-3.0).
- **Cars**, `src/those_who_run/data/cars.csv`: from ddm999/gt7info
  (https://github.com/ddm999/gt7info, MIT-0), `_data/db/cars.csv` joined with
  `maker.csv`.

## Libraries this project builds on

- **gt-telem** (https://github.com/RaceCrewAI/gt-telem), GPL-3.0: the
  telemetry decoder the engineer uses.
- **Piper** (`piper-tts`, https://github.com/OHF-Voice/piper1-gpl), GPL-3.0:
  the speech synthesis.
- **shadcn/ui** (https://ui.shadcn.com), MIT, Copyright (c) 2023 shadcn: the
  starting point of the components in `web/src/components/ui/`.

## Names

Gran Turismo is a trademark of Sony Interactive Entertainment. Track, car and
maker names are those GT7 and the tables above use, and "Advan" (in the
palette's "Advan red") is a Yokohama Rubber brand name, used descriptively.
Those Who Run is not affiliated with or endorsed by Sony Interactive
Entertainment, Polyphony Digital, Discord or Yokohama Rubber.
