# Máy chủ lab Windows: cài và chạy lời bình (VieNeu-TTS) không đụng ổ C:

Máy chủ lab (Windows, RTX) chạy phiên local: Blender, ComfyUI và lời bình. Ổ C: gần đầy (97 % lúc 2026-11-26), đĩa ảo
của WSL nằm trên C:, và Ubuntu trong WSL không có `pip` hệ thống (bộ test dùng `~/.flvenv`). Vì vậy VieNeu-TTS cài trong
một **venv trên D:**, mọi cache (pip, Hugging Face, thư mục tạm) cũng trên D:, và `tools/tts/vieneu_tts.py` được trỏ tới
venv đó bằng biến môi trường `FILM_TTS_PYTHON`. Phiên cloud không cần file này (`docs/setup-script.sh` cài sẵn).

Quy tắc của lab (CLAUDE.md, "Engine local"): **không tải hay cài gì khi chủ lab chưa đồng ý**. Claude tìm cái đã có
trước (`ls /mnt/d/Projects/Danny/.venvs/tts/bin/python`), báo dung lượng, chỉ cài khi được đồng ý. Agent
(`film-narrator`) không bao giờ tự cài trên máy chủ lab.

## 1. Bố cục trên D: (đã cài 2026-11-26: VieNeu 3.8.3 + torch 2.15 CPU, ~2,3 GB)

| Gì | Đường dẫn trong WSL | Trên Windows |
|---|---|---|
| venv TTS | `/mnt/d/Projects/Danny/.venvs/tts/` (`bin/python`) | `D:\Projects\Danny\.venvs\tts\` |
| cache pip | `/mnt/d/Projects/Danny/.cache/pip/` | `D:\Projects\Danny\.cache\pip\` |
| cache Hugging Face (model v3 Turbo ~300 MB) | `/mnt/d/Projects/Danny/.cache/huggingface/` | `D:\Projects\Danny\.cache\huggingface\` |
| thư mục tạm khi cài | `/mnt/d/Projects/Danny/.cache/tmp/` | `D:\Projects\Danny\.cache\tmp\` |
| wrapper | `/mnt/d/Projects/Danny/.tts.sh` | `D:\Projects\Danny\.tts.sh` |

Đường dẫn là của máy chủ lab hiện tại; máy khác thì đổi gốc `D:\Projects\Danny`, giữ nguyên cách làm.

## 2. Cài (một lần, chủ lab đồng ý trước; ~2,3 GB tải về, vài phút)

Trong WSL (Ubuntu), từ thư mục repo:
```bash
D=/mnt/d/Projects/Danny
mkdir -p $D/.venvs $D/.cache/pip $D/.cache/huggingface $D/.cache/tmp
export PIP_CACHE_DIR=$D/.cache/pip HF_HOME=$D/.cache/huggingface TMPDIR=$D/.cache/tmp   # không gì rơi vào C:
python3 -m venv $D/.venvs/tts            # venv tự mang pip; Ubuntu thiếu gói venv thì dùng cùng cách đã tạo ~/.flvenv
$D/.venvs/tts/bin/python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.15.0 torchaudio
$D/.venvs/tts/bin/python -m pip install -r requirements-tts.txt     # vieneu + resemble-perth (watermark)
FILM_TTS_PYTHON=$D/.venvs/tts/bin/python python3 tools/tts/vieneu_tts.py --list-voices --gender male --region nam
```
- torch CPU trước (không bao giờ bản CUDA cho TTS: GPU để dành cho Blender/ComfyUI), rồi `requirements-tts.txt` – như
  `tools/tts/README.md` §Cài đặt, chỉ khác là mọi thứ vào venv trên D:.
- `TMPDIR` trên D: vì pip giải nén wheel torch (~1 GB) vào thư mục tạm, mặc định `/tmp` nằm trong đĩa ảo trên C:.
- Lần đọc đầu tiên tải model v3 Turbo vào `HF_HOME` (~300 MB).

## 3. Chạy

`FILM_TTS_PYTHON` = python của venv. Có biến này, `python3 tools/tts/vieneu_tts.py …` tự chạy lại chính nó bằng python
đó (cùng tham số, cùng môi trường; một lần, `FILM_TTS_REEXEC=1` đánh dấu tiến trình con); biến trỏ tới file không chạy
được → thoát mã 2, không đọc gì. `HF_HOME` phải trỏ cache trên D: (không thì model tải vào `~/.cache` trên C:).

Wrapper của máy chủ lab (`D:\Projects\Danny\.tts.sh`, nằm ngoài repo; tham số chuyển nguyên):
```bash
#!/usr/bin/env bash
# vieneu_tts.py trong WSL với venv và cache trên D: (không gì trên C:)
export PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8
export FILM_TTS_PYTHON=/mnt/d/Projects/Danny/.venvs/tts/bin/python
export HF_HOME=/mnt/d/Projects/Danny/.cache/huggingface
cd "${FILM_LAB:-/mnt/d/Projects/Danny/claude-film-lab}" || exit 9    # FILM_LAB = repo (hoặc worktree) trong WSL
exec python3 tools/tts/vieneu_tts.py "$@"
```
Gọi từ phiên Claude Code local (Bash = Git Bash trên Windows; đường dẫn của tập viết kiểu WSL, tương đối với repo):
```bash
MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu --exec bash /mnt/d/Projects/Danny/.tts.sh \
  --script projects/<project>/<tập>/script.md --pron projects/<project>/pronunciation.csv --out out/<project>/<id>/vo --dry-run --strict
```
Làm việc trong worktree: thêm `FILM_LAB=/mnt/d/…/<worktree>` (`wsl.exe -d Ubuntu --exec env FILM_LAB=… bash …`).
Đo 2026-11-26: 101 câu (Q1·T3) đọc trong 191 s trên CPU.

## 4. Kiểm

`tools/doctor.sh` dòng `tts` và `tts-watermark` nhìn vào python của `FILM_TTS_PYTHON` khi biến có mặt (in `… in
FILM_TTS_PYTHON`); biến trỏ sai → WARN (FAIL cho watermark khi `--episode` đã qua G3 và có lời bình). Lưu ý `doctor.sh`
gửi một request thử tới Ark (`--quick` cũng ping): chỉ chạy khi cần, không chạy trong test.
```bash
MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu --exec env FILM_TTS_PYTHON=/mnt/d/Projects/Danny/.venvs/tts/bin/python \
  HF_HOME=/mnt/d/Projects/Danny/.cache/huggingface bash tools/doctor.sh --quick
```
Sự cố: `docs/RUNBOOK.md` ("TTS trên máy chủ lab").
