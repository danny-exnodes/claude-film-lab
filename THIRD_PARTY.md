# Third-party code

Files in this repo that contain code adapted from other projects. Each file carries a header comment naming its
source, the copyright line and what was changed. To add an entry: append a row to the table, and add the licence text
below if it is not there yet.

| File | Adapted from | Licence |
|---|---|---|
| `tools/compose/ink.js` | lemomo-ai/lemo-opuscar, `styles/ink-wash/demo/ink.js` (brush-stroke model: centreline, pressure profiles, bristles with a falling ink load, masses) | MIT |
| `tools/compose/figure.js` | lemomo-ai/lemo-opuscar, `styles/ink-wash/demo/hero.js` (joint dictionary on a 100-unit body; robe = one mass + loaded strokes) | MIT |
| `tools/audio/pluck.py` | `core/audio/pluck.py` of [lemomo-ai/lemo-opuscar](https://github.com/lemomo-ai/lemo-opuscar) (string model, guqin/pipa/koto presets) | MIT, Copyright (c) 2026 LemoLab |
| `tools/audio/sfx.py` | `core/audio/sfx.py` of [lemomo-ai/lemo-opuscar](https://github.com/lemomo-ai/lemo-opuscar) (filter, envelope, noise, compress, limit, add helpers; `thump`) | MIT, Copyright (c) 2026 LemoLab |

Only code was adapted. The demo film of that project, its characters, compositions, story, score and assets
(CC BY) are not used here.

## Licences

### MIT: lemomo-ai/lemo-opuscar

```
MIT License

Copyright (c) 2026 LemoLab

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
