# Chuyển động – Blender 3D

Chuyển động chính nằm trong `shots3d/s<NN>.json` và do Blender render: máy quay (`camera.move`: `static`, `push-in`,
`pull-out`, `pan`, `tilt`, `orbit`, `dolly`, `crane`, `track`; `from`, `to`, `target`, `lens`, `ease`) và đường đi của
model (`assets[].anim.path`, `action`). Schema đầy đủ: `tools/blender/README.md`.

| Việc | Làm ở đâu | Ghi chú |
|---|---|---|
| máy quay | `camera` của shot3d.json | một chuyển động mỗi shot, khớp cột `camera` của `shots.csv` |
| model đi theo đường | `assets[].anim.path` `[[giây, [x, y, z]], ...]` | đường chạm đất; GLB có hành động thì `anim.action` |
| sương, nắng, tàn lửa trên render | compositor, id ở `style.yaml: motion` (`tools/compose/motions.json`) | phủ lên chuỗi PNG như mọi clip |
| cử động khó (con thú bước, quay đầu) | clip local `video_engine: comfy` | `.claude/skills/film-compose-shot/references/local-video.md` |

Không trượt: model có chân đi bằng `anim.action` của chính nó; preset không có chân thì chỉ trôi, bay hoặc đứng yên.
