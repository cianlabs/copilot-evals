# Month infographics

Draw a month graphic, or a before/after bar chart, from a JSON file.

Needs Python 3, Google Chrome (headless), ffmpeg, and the Inter font.

## Make a new month

Example for M5. Run the commands from the repo root.

1. Copy `tools/graphics/data/m4.json` to `tools/graphics/data/m5.json`.
2. Set `month` to `M5` and `tab` to `M5 HUMAN-APPROVED AGENTS`. Edit `subtitle`.
3. Edit `rows`. There are 3 rows, A, B, and C. Each row has 4 cards. A card has a color (`blue`, `green`, `red`, `orange`, `purple`, `yellow`, or `white`), a title, and a body. A card may include `bars` for a small before/after chart. Edit the 6 `keys`.
4. Draw the still image. This writes `docs/img/m5_graphic.png` at 2x (2048 by 1612):

```bash
python3 tools/graphics/make_graphic.py tools/graphics/data/m5.json
```

Add `--animate` to also write `docs/img/m5_graphic.gif` and `docs/video/m5_graphic.mp4`:

```bash
python3 tools/graphics/make_graphic.py --animate tools/graphics/data/m5.json
```

`--out DIR` writes the png and the gif into that folder. With `--out`, the mp4 goes in the same folder.

## Bar chart

Copy `tools/graphics/data/m4_before_after.json` (`type` is `bars`), change the values, and run the same command. The png goes to `docs/img`.

The month names in the M1 to M6 arc live in `ARC` at the top of `make_graphic.py`.
