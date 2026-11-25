# Chuyển động – Thủy mặc 3D

Con thú là `creature` trong `cast` của shot (`tools/toon/creature.js`), timeline như rig TOON; id ở `style.yaml: motion`
khớp `tools/compose/motions.json`. Chân không trượt: mỗi bàn chân chạm đất ở một điểm tính theo quãng đường đã đi.

| Việc | Timeline | Ghi chú |
|---|---|---|
| đi / chạy | `{do: 'walk', t: [0, 3], to: [x, z]}`, `do: 'run'` | 4 chân: trình tự sau trái – trước trái – sau phải – trước phải; 6 chân: kiềng ba chân |
| quay | `{do: 'turn', t: [a, a+0.7], face: 'camera'}` | từng chân đặt lại |
| bơi | `{do: 'swim', t: [a, b], to: [x, z], wave: 0.12}` | cần `env.water`; thân uốn theo quãng đường, chân gập, để lại vòng sóng |
| bay | `{do: 'fly', t: [a, b], to: [x, y, z]}` | chân gập; có cánh thì tự vỗ, không cánh thì uốn thân như rồng |
| vỗ cánh | `{do: 'flap', t: [a, b], freq: 1.6, amp: 0.8, bias: 0.3}` | góc cánh luôn trong `TOON.WING_LIMITS` |
| xòe đuôi | `{do: 'tail-fan', t: [a, b], open: 1}` | các đuôi tách xa, dựng lên, đung đưa trễ dần về ngọn |
| quay đầu / nhìn | `{do: 'head-turn', t, yaw, pitch}`, `{do: 'look', t, at: [x, y, z]}` | cổ theo một nửa |
| thở, chớp mắt | tự động; `{do: 'breath', t, amp}`, `{do: 'blink', t}` | |

Máy quay: một chuyển động mỗi shot (`camera.move`): `orbit`, `dolly`, `crane`, bay xuyên núi `fly-through`
(`move.path`, `look: 'ahead'`); `follow` để giữ con thú trong khung. Mở cảnh: `opts.reveal` (`ink-reveal-3d`).
