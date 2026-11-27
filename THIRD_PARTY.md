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
| `tools/comfy/workflows/h3-i2v.json` | `video_minimax_h3_i2v.json` of [Comfy-Org/workflow_templates](https://github.com/Comfy-Org/workflow_templates) (subgraph "Image to Video (MiniMax H3)": node classes, input names, wiring; flattened to API format, our values). Source named in `h3-i2v.meta.json` (`source`): JSON holds no comment | MIT, Copyright (c) 2023-present Comfy Org |
| `tools/comfy/workflows/h3-r2v.json` | `video_minimax_h3_r2v.json` and `video_minimax_h3_multiframe_reference.json` (MiniMaxH3AddGuide chain) of [Comfy-Org/workflow_templates](https://github.com/Comfy-Org/workflow_templates), API format, our values. Source named in `h3-r2v.meta.json` (`source`) | MIT, Copyright (c) 2023-present Comfy Org |
| `tools/comfy/workflows/qwen-edit.json` | `image_qwen_image_edit_2511.json` of [Comfy-Org/workflow_templates](https://github.com/Comfy-Org/workflow_templates) (node classes, input names, wiring: ModelSamplingAuraFlow → CFGNorm, ImageScaleToTotalPixels, TextEncodeQwenImageEditPlus, FluxKontextMultiReferenceLatentMethod), API format, our values; the `vl` variant (ReferenceLatent), Lightning switch and output ImageScale are ours. Source named in `qwen-edit.meta.json` (`source`) | MIT, Copyright (c) 2023-present Comfy Org |
| `tools/comfy/workflows/hunyuan3d.json` | `3d_hunyuan3d-v2.1.json` of [Comfy-Org/workflow_templates](https://github.com/Comfy-Org/workflow_templates) (its subgraph: node classes, input names, wiring; flattened to API format, our values). Source named in `hunyuan3d.meta.json` (`source`) | MIT, Copyright (c) 2023-present Comfy Org |
| `tools/review/web/vendor/three/` (git-ignored, copied by `tools/review/vendor_three.py`) | [mrdoob/three.js](https://github.com/mrdoob/three.js) 0.186.1, unmodified: `build/three.module.js`, `build/three.core.js` (pinned in `tools/toon/three.lock`) and `examples/jsm/loaders/GLTFLoader.js`, `examples/jsm/controls/OrbitControls.js`, `examples/jsm/utils/BufferGeometryUtils.js`, `examples/jsm/utils/SkeletonUtils.js` (pinned in `tools/review/three-examples.lock`) | MIT, Copyright © 2010-2026 three.js authors |

Only code was adapted. The demo film of that project, its characters, compositions, story, score and assets
(CC BY) are not used here. From Comfy-Org/workflow_templates only the graph structure of the two MiniMax H3 templates
and of the Qwen-Image-Edit 2511 and Hunyuan3D 2.1 templates was adapted; no model weights or template thumbnails
are in this repo.

Model weights the local workflows load (on the owner's PC, never in this repo) have their own licences:
`hunyuan_3d_v2.1.safetensors` (workflow `hunyuan3d`, Comfy-Org's repackaging of Tencent Hunyuan3D 2.1) is under the
**Tencent Hunyuan 3D 2.1 Community License**: it does not apply in the European Union, the United Kingdom or South
Korea, and commercial use has conditions (monthly active users, attribution). A mesh made with it (or a model rebuilt
from that mesh) carries that licence in the episode's `ASSETS.md`; read the licence that ships with the model before
publishing. `docs/MODELS.md` lists the other local models.

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

### MIT: Comfy-Org/workflow_templates

Licence file checked 2026-11-25 at https://github.com/Comfy-Org/workflow_templates (`LICENSE`): MIT License,
"Copyright (c) 2023-present Comfy Org"; the permission and warranty text is the MIT text above, word for word.

### MIT: mrdoob/three.js

Licence file of the installed package (`three/LICENSE`, 0.186.1) checked 2026-11-25: The MIT License,
"Copyright © 2010-2026 three.js authors"; the permission and warranty text is the MIT text above, word for word.
`tools/review/vendor_three.py` copies the files unmodified (sha256-pinned), so their own headers stay with them.
