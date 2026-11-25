# Thủy mặc 3D (`thuy-mac-3d`)

Trạng thái: **draft** · Phong cách số 12 của bộ vẽ bằng code · Kế thừa: `cinecode:ink-wash` · Engine: **3D (three.js)**
· Bảng màu: `styles/thuy-mac` · Dữ liệu máy đọc: `style.yaml` · Chuyển động: `motion.md` · Âm thanh: `sound.md`

Style này dùng cho tập **`method: code`** cần dị thú và phong cảnh thủy mặc mà **không gọi model tạo ảnh hay video**
(#35): mọi con thú, núi, nước là model 3D dựng bằng code (`tools/toon/creature.js`, `tools/toon/ink3d.js`), chuyển động
3D bằng code, ngân sách 0 ảnh / 0 giây. Hướng dẫn chung: `.claude/skills/film-compose-shot/references/code-method.md`.

## Tinh thần

Tranh mực trên giấy dó cũ, nhưng máy quay đi được quanh con thú. Thân thú là các lớp mực loang theo ánh sáng (ba bậc,
ngưỡng xê dịch theo thớ giấy, mực đọng ở mép mỗi lớp), lưng đậm hơn bụng, rìa thân có nét khô đứt quãng. Viền mực
dày ở gần, mảnh dần ở xa. Núi ba tầng xa – giữa – gần, càng xa càng nhạt (tam viễn), mặt núi có nét thuân (皴) chạy
xuôi sườn và chấm rêu gần đỉnh, chân núi tan vào sương. Mặt nước là giấy trống với vài nét ngang; con thú bơi để lại
vòng sóng. Ánh nắng thấp, ấm (ochre) từ bên phải, không vẽ đĩa mặt trời; đúng một điểm son (mắt con thú hoặc triện).

## Khi nào dùng

Truyện dị thú, thần thoại, Sơn Hải Kinh kể bằng hình 3D; cảnh cần máy quay 3D thật (vòng quanh con thú, bay xuyên
núi) mà style ảnh `thuy-mac` không làm được.

## Tránh

Thân thú tô kín màu đen (mất các lớp loang); nhiều điểm son; nền trời có màu; sương vẽ dày che hết núi; máy quay
quá thấp nhìn ngang mặt đất (mất chiều sâu ba tầng núi).

## Thông số render (`style.yaml: render`)

| Khóa | Giá trị |
|---|---|
| `engine` / `look` | `"three"` / `"ink-wash-3d"` |
| `hold` | `1` (24 hình/giây) |
| `opts.line` | độ dày viền mực (px ở 1080p, gần máy quay), mặc định 2.4 |
| `opts.steps` | số bậc mực trên thân (1–4), mặc định 3 |
| `opts.glow` | nắng ấm bên phải (0 = tắt), mặc định 0.35 |
| `opts.grain` / `opts.bleed` | thớ giấy, mực loang vào giấy (0 = tắt), mặc định 1 |
| `opts.reveal` | `{at, dur}`: cảnh hiện ra như mực loang (motion `ink-reveal-3d`) |
| `opts.ripples` | `[{at: [x, z], t, amp}]`: vòng sóng đặt tay (motion `water-ripple`) |
| `env` | `water` (mặt nước ở y = 0), `mist` (0–4 dải sương), `bands` (0–3 tầng núi), `seed` |

`render.palette` ghi đè màu của look (`ink`, `paper`, `ochre`, `grey`, `accent`). Con thú giữ bảng màu riêng
(`palette.body`, độ đậm của mực thân lấy từ độ sáng màu này; `palette.eye` = điểm son).

## Con thú

`tools/toon/demo/creatures/`: `mac-loc` (bốn chân, ba mắt, sừng nhánh, ba đuôi xòe), `van-dieu` (hai chân, cánh,
năm đuôi lông dài), `luc-tuc-ngu` (sáu chân, thân dài bơi uốn). Thiết kế riêng cho lab. Con thú mới: chép một file,
sửa **Thông số model** (`code-method.md` §8).

## Quan hệ với `thuy-mac`

Cùng series, cùng bảng màu và âm thanh. `thuy-mac` là style ảnh (Seedream, lớp tranh 2.5D); `thuy-mac-3d` là bản vẽ
bằng code. Một tập chỉ dùng một phương pháp (`EPISODE.md: method`), nên không trộn hai style trong một tập.

## Duyệt

`python3 tools/toon/toon.py turntable --creature mac-loc --out review/turntable-mac-loc.png` và một clip của style.
Chuyển `status: stable` khi có tập đầu tiên qua G2 bằng style này (ghi vào `examples.md`).
