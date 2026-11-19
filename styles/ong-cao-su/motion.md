# Chuyển động – Tay ống cao su

Mọi chuyển động là hành động của rig TOON (`tools/toon/motion.js`), ghi trong timeline của shot; id ở `style.yaml: motion`
khớp `tools/compose/motions.json`. Chân không trượt (bước chân tính theo quãng đường), thân không xoay kiểu cắt dán.

| Việc | Timeline | Ghi chú cho Tay ống cao su |
|---|---|---|
| đi vào khung | `{do: 'walk', t: [0, 1.7], to: [0, 0]}` | sải mặc định 0.34; chạy: `do: 'run'` |
| quay về máy | `{do: 'turn', t: [a, a+0.35], face: 'camera'}` | bước chân đặt lại, không xoay trên một điểm |
| vẫy / reo / chỉ | `wave`, `cheer`, `point` | lớp phủ lên tay, mờ vào/ra 0.2 s |
| nhảy | `{do: 'jump', t: [a, a+1.2], height: 0.35}` | nén – bật – bay – tiếp đất có nén |
| nhún theo nhịp | `{do: 'bounce', t: [a, b], bpm: 120}` | cùng BPM với nhạc (bắt buộc với style này) |
| nhìn theo | `{do: 'look', t: [a, b], at: [x, y, z]}` | chỉ mắt |

Nhịp hình: `hold: 2` (12 hình/giây, bước đôi). Máy quay: một chuyển động mỗi shot
(`camera.move`), ease `inOut`; theo nhân vật bằng `follow: 1`.
