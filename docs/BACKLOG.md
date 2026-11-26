# Backlog – việc còn nợ sau đợt kiểm toán 2026-11-10

Sinh từ báo cáo của đội agent (11 lượt kiểm toán, 10 gói triển khai, 10 lượt review). Sửa xong mục nào thì xoá mục đó.

## Cần chủ dự án quyết

- Lambda: the hardened worker was redeployed on 2026-11-11 (Active, 900 s, CodeSha256 matches the repo). No job has run on it yet; whether the runtime accepts the conditional write (IfNoneMatch) is still unverified until the first job.
- BytePlus credit was exhausted on 2026-11-11 (owner): every paid item below waits for a top-up.
- rembg model for L4/P layers: matte.py has been running bria-rmbg by accident (1 GB download, 9 GB RAM, weights believed to be non-commercial; licence text not verified). The fix makes u2net the explicit default as documented. Decide whether u2net stays or a heavier model is adopted (then prefetch it and clear its licence); mattes made so far may differ from new ones.
- Narration in the pipeline: confirm the proposed placement without a new stage number or gate (voice audition before G1 when the series has no voice, voice picked by ear at G1, draft narration right after G1, takes heard at G3). The film-narrator agent ships now; the stage rows, hand-off tool, voice block in SERIES.md and vo/ bundling wait for this answer.
- Issue #8: drop the three-model listening comparison (VieNeu 0.5B is excluded by its voice licence) in favour of an in-family voice audition, or keep it as a separate low-priority item.
- Drive pull side: allow one free live download in a session with the connector to test whether a PostToolUse hook can save download_file_content to disk and replace the base64 in context; and, if it works, whether to wire that hook into .claude/settings.json. The same session can confirm folder creation with contentMimeType.
- Paid media that is not yet approved exists only in the container while a gate waits for you: allow work-in-progress bundles to Drive before approval, use the Lambda S3 bucket as a safety net, or accept the risk explicitly.
- Should requests that Ark rejects before generating (HTTP 401/403/404/429, 400 InvalidParameter) stop counting against the episode caps? Today every failure counts, by rule.
- Pre-G2 spending caps enforced by ark.py (for example at most 8 images and 0 video seconds until G2 is dated): wanted, and with which numbers?
- CI: add .github/workflows/tests.yml by hand in the GitHub web UI (copy docs/ci/tests.yml; a cloud session cannot push workflow files). The suite has never run on a GitHub runner: the Chrome pixel tests run there for the first time.
- Where character lock images are recorded: a prompts.csv row under a new naming rule, or a key-images table in CHARACTER.md with no prompts.csv row.
- Nhật ký push-time column: is it the time the push of that stage started (written before the push so EPISODE.md goes up once), or should the column be dropped?
- Behaviour changes to accept with this round: `ark.py video` defaults to 720p; an existing output file is refused by ark.py, matte.py and upscale.py unless --overwrite; matte.py writes to plates/matte/ by default and runs u2net; a missing budget.yaml, a stage past an unpassed gate and a final render of the wrong size or length become check ERRORs; `drive_sync.py snapshot` refuses when unpushed local changes exist; tts exits 2 on a script line without a valid mark.
- Issue #3: supply the ChatGPT reference images for the comparison item, or drop that item.
- Scope of P part-layer rigs and the ink reveal in the compose kit (compose-10), and the reasons behind fixed limits such as three parallel plate-makers and two G3 revision rounds (docs-13).

## Chạy thử có phí đã chuẩn bị sẵn công cụ

- Issue #4, clip as a layer (prepared by seedance-clip-layer and compose-kit-tests): production session, director delegating to film-animator. One 5 s Seedance clip at 720p from a keyframe.py start frame that passed `keyframe.py --check`: 5 video seconds from the episode budget. Then free: `matte_seq.py` once with --method chroma and once with --method rembg on the same frames gives the flicker, haze and alignment numbers that close the chroma-versus-rembg question; re-check the tool's WARN thresholds on this clip.
- Issue #4, 1080p timing: either make that same clip at 1080p (no extra spend, if the owner accepts skipping the 720p trial) or one more 5 s clip = 5 more video seconds; read the wall time from the ledger rows.
- Issue #13 step 3, L1 at 4K through the Lambda (prepared by lambda-hardening): main session, only after the free redeploy of the hardened worker. One Pro image at an explicit landscape size such as 3840x2160 via `ark.py lambda-job prepare` = 1 image under the models.dola-seedream-5-0-pro-260628 cap. Recommended second image: one Pro 2K with --ref of a locked character, which exercises the never-run refs path and the state-variant item of issue #3.
- Issue #3, seed and negative prompt (scoring tool NOT built this round, judged by eye): production or lab session, 4 lite images at 1024x1024 with --budget/--ledger of a lab folder (same prompt and seed twice, another seed, same seed plus --negative).

## Engine local (Blender, ComfyUI + MiniMax H3) – việc tiếp

- Kiểm giấy phép thương mại của MiniMax H3 trên model card và ghi vào `docs/MODELS.md` trước khi đăng phim kiếm tiền.
- Hằng số dự báo trong `status.py`: H3 bản cuối đã đo (713 s GPU cho clip 5,17 s 1344×768, 20 bước); phút Blender mỗi
  shot và H3 bản nháp 864×480 vẫn là ước lượng: thay bằng số đo sau vài tập.
- H3 bản cuối ~34 s mỗi bước vì model 20 GB không vừa VRAM 16 GB: thử bản DiT nhỏ hơn hay `--turbo` cho nháp, và đo xem
  bản nháp 864×480 có đủ để duyệt chuyển động trước khi render bản cuối không.
- `comfy.py run` chỉ in "running" + thời gian: đọc tiến độ từng bước qua websocket `/ws` (không thêm thư viện).
- Prompt khi có `--last`: H3 first-last-frame có cần dòng neo cho `<Picture 2>` ở cuối clip không? Chưa kiểm; hiện chỉ có
  dòng neo khung đầu.
- Ghim sha256 các file model H3 trong `tools/comfy/comfy.lock.json` (`models --verify`); hash ~45 GB một lần.
- Khung dọc (9:16) cho H3 (`--res` thêm preset dọc).
- Model đã có trên máy nhưng chưa nối: ảnh tĩnh local bằng Qwen-Image 2512 / Z-Image Turbo (thay Seedream, miễn phí);
  phóng clip H3 1344×768 → 1920×1080 bằng SeedVR2; LTX-2.3 điều khiển bằng pass depth/line của Blender; Wan Animate 2.
- Blender: nhân vật glTF có khung xương (armature) chưa thử, mới thử action cấp object; máy chủ lab chưa có `ffmpeg` trên
  PATH (mp4 do encoder của Blender làm; nhánh ffmpeg và nhánh EEVEE→Cycles mới thử bằng fake); look phẳng trong Cycles
  không đổ bóng.
- `check_episode.py`: kiểm nội dung `ASSETS.md` (mỗi `A-<asset>` trong `shots.csv` có một dòng nguồn + giấy phép).
- Grade thuỷ mặc (`tools/compose/grade.py`, issue #70): tham số `grade:` của `chan-thuc-blender` là điểm khởi đầu, chưa
  duyệt trên render Cycles thật; chưa thử pass depth/mask thật của Blender (chỉ pass giả cùng định dạng). Còn nợ: dựng lại
  mask khi khung đã sửa bằng model ảnh (hình lệch khỏi mask Blender: ROI + tương phản + hình thái học, bản tham khảo cần
  scipy); chạy song song nhiều khung (~0,6 s/khung 1080p, một lõi); mp4 đầu ra không cùng byte giữa hai lần (x264), chỉ
  chuỗi PNG được bảo đảm.

## Lỗi reviewer xác nhận nhưng chưa sửa

### ark-paid-guards
- tools/ark.py:330 load_budget: `images: .inf` is accepted as a cap (an explicit unlimited cap). The spec only asks for a number >= 0, so left as is; the integrator may want check_episode.py to warn on it.


### matte-safety
- tools/layers/matte.py:276-277 (not fixed: outside the spec, which only refuses --preview equal to IN or OUT): --preview silently replaces any other existing file, so a mistyped preview path that names another plate still destroys it. Refusing an existing preview would break the routine re-run of the same preview file; needs an owner decision.
- tools/layers/matte.py:276 (not fixed: behaviour older than this package): a --preview in a folder that does not exist fails with a FileNotFoundError traceback after OUT has been written; with the new guard the re-run then needs --overwrite.
- tools/layers/matte.py:270 (not fixed: minor): OUT that is a directory, with --overwrite, ends in an IsADirectoryError traceback (exit 1, nothing destroyed).
- tools/layers/anchors.py:92-93 (not fixed: older than this package, not in the spec): an anchors.json whose per-file value is not an object (`{"<file>": [1,2]}`) gives an AttributeError traceback in set; the file is left untouched.
- tools/layers/anchors.py:131 (not fixed: older than this package): `mark` still crashes with `ValueError: cannot convert float NaN to integer` on an anchors.json that already contains NaN written by the old code; `set` can no longer produce such a file.
- tools/layers/upscale.py:61 (not fixed: not in the spec): a missing IN is still a FileNotFoundError traceback (exit 1), unlike matte.py which now prints `matte: cannot read ...`.
- tools/layers/anchors.py:25-28 (not fixed: judgment call): an anchors.json with a UTF-8 BOM is reported as `not valid JSON (Unexpected UTF-8 BOM ...)` exit 1 rather than read; the message is accurate and the file is untouched.



### lambda-hardening
- lambda/ark_image_worker.py:160-163 (pre-existing, not in the spec): `ref_keys` given as a string instead of a list is iterated character by character -> failed, sent:false, error 'ref not in bucket: r: ...'. Nothing is sent or billed; `lambda-job prepare` always writes a list, so left alone.
- lambda/ark_image_worker.py claim(): when the runtime's botocore rejects IfNoneMatch the worker silently uses the non-atomic read-then-write fallback and no status field says which path ran (the engineer reported this too). Not verifiable without AWS; not fixed.
- lambda/build_deploy.py program, HeadObject `except Exception` (pre-existing): any HeadObject error, including throttling or AccessDenied, is reported as zip-missing. Harmless (nothing is created), not fixed.
- lambda/README.md does not mention the SSE-KMS exception of the zip-stale check (the bucket this program creates uses the default SSE-S3, so it does not apply to the deployed setup); left out to keep the doc hunk untouched.

### check-episode-gates
- tools/check_episode.py main(): when cmd_episode itself fails while writing --out (for example --out names a directory), the report is printed twice and the write is retried once before 'report not written'. Exit code 1 is correct; cosmetic only.

### env-doctor
- .claude/hooks/session-start.sh steps 1-2 run before `trap report EXIT` (as the spec says): an unwritable ARK_DIR or CLAUDE_ENV_FILE still ends the hook with exit 1 and no report. Not fixed: spec places the trap after the variables step.
- .claude/hooks/session-start.sh run from a linked worktree still writes FILM_LAB/CINECODE_FORMATS/CHROME_PATH pointing at the worktree into CLAUDE_ENV_FILE (pip and the stamp rewrite are skipped in a worktree since ci-hygiene). Needs a decision by the integrator, not a defect against the spec.

### episode-status
- tools/status.py read_budget / shots_section: an empty budget.yaml loads as 'no caps' with no note and passes the G1 line `budget.yaml present and loadable (ok)`; an empty shots.csv gives an empty SHOTS section with no note. Both mirror what ark.load_budget accepts today and the spec does not ask for more; the other package that makes load_budget stricter will turn the first into a note. Not fixed.
- tools/status.py:552 print: with PYTHONIOENCODING=ascii the Vietnamese stage name raises UnicodeEncodeError (traceback). LANG=C / LC_ALL=C works (Python coerces to UTF-8). Contrived and shared by the other tools; not fixed.

### seedance-clip-layer
- tools/layers/matte_seq.py main loop (around line 296-303): when a frame fails mid-run (unreadable, or a size different from the first frame) the frames keyed so far stay in OUT_DIR and with --overwrite the previous keyed set is already deleted; the rerun then needs --overwrite. Keyed frames are derived data (the paid .mp4 and raw/ are never touched), so I left it; the message now says so.
- tools/layers/matte_seq.py Keyer.__init__ (line ~123): --method rembg with the model file cached but the rembg package not importable ends in an ImportError traceback (exit 1) instead of a usage message. Not reachable in a session where session-start.sh ran; not fixed.
- tools/compose/keyframe.py generation mode (line ~141): any existing OUT other than the plate is overwritten without a flag, as before this package (the spec says to keep current behaviour). A start frame is free to regenerate, but an approved start frame version can be replaced by rerunning with the same name.
- tools/compose/keyframe.py (line ~155): WARN KEY NEAR SUBJECT fires on a single opaque pixel within distance 60 of the key; on real plates with a few stray despilled edge pixels it may fire often. Matches the spec wording; threshold not calibrated on a real plate.

## Phần của gói việc chưa làm

### ark-paid-guards
- Nothing from the seven spec items was cut.
- Deviation to decide on: the ledger_required check moved from reserve() into the new checked_budget() (same message, same exit 2), so that it too is refused before the output folder is created. The spec said not to touch ledger_required beyond what is listed; tests/test_lambda.py passes unmodified. reserve() now takes the already validated budget as a keyword argument (budget=None) instead of loading it itself; all three callers pass it.
- Deviation to decide on: the commit carries no Co-Authored-By / Claude-Session trailer, following the package rule 'no model names or session links in commits' over the harness attribution default. Add the trailer at integration if the repo wants it.
- The `output exists` message does not mention --overwrite (deliberate, so agents bump the version instead); the flag is in --help and in CONVENTIONS §7.
- Not verified here: tools/doctor.sh and tools/status.py against the new ark.py (other packages). Names they use (call, VIDEO_DEFAULT, IMAGE_FAST, LAMBDA_DEFAULT, ping format, ledger_rows, billed_requests, units, req_id, FINAL, load_budget) are kept, but load_budget() now exits 2 on an invalid budget.yaml instead of returning a loose dict, and units() clamps at 0.

### drive-push-safety
- Nothing in the spec was cut. Left out on purpose, as the package file says (integrator to track): (a) templates/project/README_CauTruc.md still puts ledger.csv in the dated folder - PR #25 rewrites that row, fix after it merges; existing projects fix their Drive README. (b) The folder-creation wording in the plan (mimeType vs contentMimeType) is unchanged - waits for one real folder creation.
- Items from findings_detail that are NOT in the spec and were not implemented: plan --brief/--show, `bytes` per entry and size WARN, refusing --include-out of another project (--allow-foreign-out), record refusing UNMAPPED files, snapshot --expect sizes.json, the `write` pull command, bundle --wip (needs owner decision), tools/status.py MEDIA section.
- Commit trailer: the task says no model names or session links in commits, but the session's attribution rule requires the Co-Authored-By / Claude-Session trailer and every existing commit on this branch (e.g. 2740dac) carries it, so commit 5e4bb37 has the same two trailer lines. Strip them when integrating if unwanted; the subject and body contain none.
- CLAUDE.md / README.md / RUNBOOK / CHANGELOG not edited (shared files) - see readme_claude_notes, runbook_rows, changelog.

### matte-safety
- layers-1 proposal items outside the spec were not done: no cross-process flock around rembg predict, and tools/doctor.sh / .claude/hooks/session-start.sh / docs/setup-script.sh still hardcode u2net (not owned files; they agree with the new default, but would not follow FILM_REMBG_MODEL).
- No drive_sync test asserting that `.anchors.json.lock` is not planned for upload (check-13 proposal): tests/test_drive_sync.py is not an owned file; the property is covered from the anchors side only (lock is a dotfile, which drive_sync.py:71-72 already ignores).
- anchors.json is still written with mode 0600 (mkstemp), noted as harmless in the audit and not in the spec.
- Old `anchors.json.lock` files already in working copies or on Drive are not removed or migrated by the code (nothing is deleted); see the RUNBOOK row.

### tts-correctness
- Nothing from the spec was cut. Not in the spec and deliberately not done (finding proposals the spec dropped): the --fit mode, docs/TTS.md, normalisation rule fixes (fractions, dotted decimals etc. are only flagged by residue when a digit is left), spoken_sha, calibrating --rate from an existing log, a narration stage row / chart node in WORKFLOW and film-pipeline, `vo` in CONVENTIONS §1, a check_episode WARN.
- Known gap left as specified: STALE and --check compare the script text only. A change to pronunciation.csv or --numbers changes `spoken` without changing `text`, so such takes are not reported as stale; re-render after editing the pronunciation map.
- tools/doctor.sh was not run (not required by this package; it reports the ark.py link as FAIL in a worktree).

### compose-kit-tests
- Optional Chrome smoke test (demo plates -> inline --init -> capture.mjs --verify prints 'deterministic: yes'): not written. Chrome is installed here (/usr/bin/google-chrome), but the spec marks it optional and nothing in this package was run in a real browser; the kit changes are verified only against the mock canvas.
- tools/doctor.sh itself was not run (it reports the ark.py link as FAIL in a worktree); only its compose-kit step was reproduced by hand on a temp copy of the installed cinecode template, with the result described under done.

### lambda-hardening
- REDEPLOY NOT DONE (by design, cannot be done here): the function on AWS still runs the OLD worker (300 s timeout, cached key, no sent/deadline/worker_sha256, non-atomic guard, no ListBucket). Before the next paid job the main session must, through the AWS connector: `python3 lambda/build_deploy.py > out/deploy_run.py`, upload out/ark_image_worker.zip to deploy/ark_image_worker.zip with a presigned URL (curl -fsS -X PUT), run the NEW program with aws___run_script, and see state Active + code_matches_repo true. Expected values for this head: CodeSha256 /WN8gHjnmfILqJdjPUPEf7ZL1N4SL93H7BOujPX9eNw= , worker sha256 8aeee5d4b1dce09948e19b3a11b0d9a5ce55b1c889effba3865547279d52303b (both change if the integrator touches lambda/ark_image_worker.py; re-read with `--check`). Running the new program without uploading the new zip gives zip-stale (function untouched; the role policy is still rewritten with ListBucket).
- Whether the Lambda python3.13 runtime's bundled botocore accepts IfNoneMatch on PutObject was not verified (no AWS access here). If it does not, the worker silently uses the read-then-write fallback (today's non-atomic behaviour, but with the stricter existing_status). Nothing reports which path ran.
- Shared files left for the integrator (not edited): CHANGELOG.md, README.md line 38, docs/MODELS.md pro row, docs/releases/*, docs/RUNBOOK.md row 39.
- Commit trailers: the commits end with the Co-Authored-By / Claude-Session trailer lines, as the session's attribution reminder requires and as every existing commit in the repo does; the package text asked for no model names or session links in commits. The integrator can strip them when squashing if that rule is meant to cover trailers.

### check-episode-gates
- Nothing from the spec was cut. Deviations from the acceptance list of touched lines, all deliberate and small: (1) the last three lines of check_media changed (ledger header now read through new helper ledger_head) because spec item 6 requires reading the ledger through read_text, although the spec also says not to edit the body of check_media; the first lines, where PR #25 works, are untouched. (2) read_csv: its except tuple now names CheckError instead of UnicodeDecodeError (one line), otherwise a non-UTF-8 CSV would have regressed to an 'internal' error. (3) cmd_episode and cmd_style take an optional second parameter `rep` (first line of each changed) so main() can still print and write the partial report after an exception; the --out writing code is duplicated in main()'s except branch rather than factored out of cmd_episode's tail, to keep cmd_episode's existing lines unchanged for the merge with PR #25. (4) The module docstring got one added paragraph (no existing line changed).
- Not in this package (only mentioned in findings_detail, not in the spec): tools/episode_gate.py, hardening ark.load_budget, a `--` change in film-script SKILL.md line 12.

### env-doctor
- From finding infra-1, not in the spec: no `ark.py probe-video` subcommand and no automatic cancel (DELETE) of an accepted probe task; doctor only prints the task id and says to cancel it in the Ark console. tools/ark.py was not edited.
- From finding infra-3: `ark.py ping --timeout` was not added (ark.py is owned elsewhere); doctor wraps the ping in `timeout 20` and the probe in `timeout 60` instead.
- Worktree run of the hook still executes the env exports (pip and the stamp rewrite are skipped since ci-hygiene). Not changed; flagging it for a decision.
- doctor.sh full mode and --quick were never run against the real Ark host (hard rule: nothing touching outside systems); all runs used a closed port or the local fake server. The Shutdown status spelling is taken from ark.py's ping code, not from a live listing.
- The real /opt/byteplus/ark.py link is still broken (see the first item under done): I could not restore it.
- Commits carry no Co-Authored-By / session trailer, following the package rule 'no model names or session links in commits'.

### episode-status
- Nothing from the spec was cut. Deliberately out of scope as the package says: --brief, Nhật ký tail, qc parsing, render probing, Drive plan, plate-maker split, bundle command hints.
- CLAUDE.md, README.md, CHANGELOG.md, docs/RUNBOOK.md not edited (shared files): see readme_claude_notes, changelog and runbook_rows.
- tools/doctor.sh was not run (it is not touched by this package).

### seedance-clip-layer
- Nothing in the spec was cut. Left for the integrator as the package says: README tool table, CLAUDE.md tool list, RUNBOOK row, CHANGELOG.
- Stage-table order (clips in stage 6 before compositing in stage 7) in docs/WORKFLOW.md and the film-pipeline skill was left untouched, as specified; the order is stated only in seedance-layer.md and the two agent files.
- Nobody writes the clip's prompts.csv row yet (deferred by the package; seedance-layer.md §4 still says to record it).
- No real Seedance clip was keyed (paid): every WARN threshold (HAZE 1.0, FLICKER 2.0, BG_FLAT 12, IoU 0.8) is calibrated on synthetic frames and one lavfi/libx264 clip only.
- The real rembg model was never run through matte_seq.py (tests use a fake module); only the one-session wiring and the not-cached refusal are proven.
- The 120-frame timing was not re-measured after the last speed-up (see done); the 42.7 s figure is from before it.

## Hai phương pháp dựng (#28): việc còn nợ

### Reviewer xác nhận nhưng chưa sửa
#### method-field
- tools/check_episode.py:508: an ai_motion cell holding only separators (` ; `) counts as 'has ai_motion' under method layers. It is literally non-empty, so this matches the spec; the fix for the user is to empty the cell. Left as is.
- tools/check_episode.py:415-421: the layers budget rule recognises a video model only by 'seedance' in the model id (as the spec says). A `models:` cap for a video model with another name would not be flagged. `video_seconds: 0` is still enforced, and ark.py is not changed by this package.
#### layers-method-docs
- .claude/skills/film-script/SKILL.md section 4a states '`check_episode.py` báo ERROR nếu có' (ai_motion in a layers episode). At this base check_episode.py has no method check at all; true only once the method-field package is merged.
- .claude/skills/film-compose-shot/SKILL.md and references/layers-method.md link to references/layers-character.md, which does not exist at this base (written by the compose-character package), and name COMPOSE.smoke.plume, COMPOSE.fire.flames, COMPOSE.fire.glow, rig `cloth`, rig `poses`, which are not in tools/compose at this base. Dangling until the sibling packages land; names must be re-checked then.
- styles/thuy-mac/style.yaml `motion:` lists five ids missing from tools/compose/motions.json: `check_episode.py style styles/thuy-mac` goes from 0 to 5 warnings (0 errors). Disappears only when compose-atmosphere/compose-character register the ids; otherwise revert that hunk.
- Naming collision: `L4b` is a pose-plate layer code in layers episodes (every tool accepts L4b–L4z since episode-schema; a pose plate in a seedance episode is a WARN) and also the PLATES key of the Seedance seq layer printed by tools/layers/matte_seq.py:361. Rename the seq key (e.g. `L4clip`) in matte_seq.py and the seedance docs.
- styles/thuy-mac/prompts/character-cel.txt embeds {style_block} (ink-wash, 'wet-on-wet ink gradients, visible paper grain, high detail') inside a prompt that asks for flat fills, no gradients, no texture. Contradictory tokens may pull the model toward painterly output; untested (no credit), and the file/STYLE.md say so. To be judged on the first paid lock image at G2, not fixable by review.
- styles/_template has no character-cel/pose-set templates and no layers rows in motion.md (engineer's stated not_done; spec made it optional).
- docs/WORKFLOW.md mermaid diagram still draws stage 6 unconditionally (table and new section say seedance-only); docs/CONVENTIONS.md section 6 list of known code_motion ids still shows the eight old ids.
#### compose-atmosphere
- tools/compose/foliage.js:44-55 with strip-warp.js:50-59 (not owned by this package): when the root is a point inside the box, the part of the box before the root stays in the body AND is redrawn by the still strips, so semi-transparent pixels there (soft ink-wash edges) are composited twice and read slightly denser. This is strip-warp's existing joint design (two strips of overlap by default); with a root point it covers the whole trunk part of the box. Not fixed: needs a change in strip-warp.js or a look at a real frame.
- compose-api.md line 245 says the inlined kit is '~71 KB'; after the review fixes the 12 files are about 73 KB. Cosmetic, not pinned by a test.
- Not verified in a real browser by me: all checks ran on the fake canvas (node). The engineer's claim of one headless Chrome frame, capture performance and `capture.mjs --verify` on a film using the new modules remain unmeasured.
#### image-batch
- tools/ark.py image_batch worker (re-check before batch_row): two runs of the same CSV at the same time can still both send a row that is in flight in both, and the later save replaces the earlier file. The fix narrows the window from the whole batch to one request; closing it needs a per-output lock. Not fixed: `image` has the same window and it is a larger change.
- tools/ark.py read_jobs (phase 1): an `out` whose parent path is an existing file is not caught in validation. It surfaces in phase 3 as `stopped: <id>: FileExistsError`, exit 2, all remaining rows not started. Nothing is sent or lost, but it contradicts the claim that every problem is listed in phase 1. Not fixed: cosmetic.
- tools/ark.py read_jobs: an `out` that names an existing non-image file (the jobs CSV, the ledger, budget.yaml) is silently reported as `skip <id>: output exists`. Nothing is sent or overwritten. Not fixed: harmless.
- Design, not a bug: re-running a batch re-sends rows whose earlier attempt ended `failed`, `cut-502`, or was left `pending` by a killed process, because their output file is missing. The earlier attempts stay counted against the caps and the help text warns about it, but CLAUDE.md says a cut-502 is not retried automatically. The integrator should make sure the skill and RUNBOOK text tell the director to read the failed and cut-502 rows before re-running.
#### status-forecast
- tools/status.py against() (~line 386): when a cap is already overspent (left < 0) and nothing is left to make, the line reads e.g. `-2 left · fits`. Arguably correct (nothing more to pay; BUDGET shows the overrun) but reads oddly. Read from the code, not run. Not changed.
- tools/status.py clip_seconds (~line 350): no upper bound. `to_s=1e308` is finite, so it is forecast as one clip and printed as a 309-digit integer (no crash, verdict OVER). A shot longer than Seedance's 30 s maximum is forecast as one clip of its full length. Cosmetic / not in spec.
- tools/status.py --json: `method: .nan` in EPISODE.md is emitted as bare `NaN` (not strict JSON). Same pre-existing behaviour for other front-matter values such as length_s; not changed.
- ai_motion values such as `-` or `none` count as motion (clip planned, or CONFLICT in layers). This is the existing convention of the SHOTS section (any non-empty cell); not changed.
- Duplicate layer codes in one `layers` cell (`L1;L1`) and duplicate shot rows are each counted (existing coverage logic); left to check_episode.
#### compose-character
- tools/compose/cloth.js (cut + feather): in the first `feather` px (6 % of the length) the faded body and the cloth overlap, so translucent pixels there are denser (alpha 128 measured up to about 190 at the root line, falling back to 128), and `cloth: false` does not reproduce a translucent plate in that zone. Opaque content is exact. L4 in thuy-mac is rembg with a solid body, so only 1-2 px edge pixels are affected; documented in layers-character.md.
- tools/compose/cloth.js:78-86: two overlapping cloth boxes on one plate: the second crop is taken after the first cut, so shared pixels belong to the first box, but the first box's faded feather strip is also captured by the second crop (a faint ghost). Not fixed (boxes are documented as non-overlapping).
- layers-character.md section 4 item 6 names `python3 tools/ark.py image-batch <jobs.csv>` with --budget and --ledger, and section 1 names `method: layers`; neither exists at this base. The integrator must check the flags against the real command.

### Phần của gói việc chưa làm
#### method-field
- Nothing in the spec was skipped. Deliberate deviation to flag: the spec asked only for a comment in templates/episode/budget.yaml, but I also changed the template value `video_seconds: 30` -> `video_seconds: 0`, because the episode template now says `method: layers` and the two templates copied together would otherwise fail the checker at stage 0. Revert that one line if you want the old default; test_templates_pass_together would then have to go.
- Commit trailers: the task said no model names or session links in commits, while the session's attribution rule requires the Co-Authored-By / Claude-Session trailers and every earlier commit in this repo carries them. I kept the trailers (the message body has neither); strip them at integration if you want them gone.
- Only tools/check_episode.py reads `method`. tools/status.py, tools/ark.py (refusing `video` for a layers episode), the skills, the agents and docs/WORKFLOW.md were outside this package and are unchanged.
- The checker does not enforce 'never changed after G1 without asking'; that rule is documentation only (template comment and CONVENTIONS §5).
#### layers-method-docs
- styles/_template untouched (spec: only if needed; no test or check required it). A new style therefore has no character-cel/pose-set placeholders and no layers rows in its motion.md template.
- No hunk in CONVENTIONS section 3/5/6/7 (left to method-field and image-batch packages to avoid conflicts). The section 6 bullet listing known code_motion ids still shows only the eight old ids: integrator should add smoke, fire, foliage, cloth, pose-cycle there once motions.json has them.
- Mermaid diagram in docs/WORKFLOW.md not changed (stage 6 still drawn unconditionally); the stage table row and the new section say it is seedance-only.
- Numbers in styles/thuy-mac/motion.md for the five new ids and both new prompt templates are untested starting values (no credit on the account, nothing was generated); the files say so.
#### compose-atmosphere
- Signature deviation from the spec text: the calls are COMPOSE.smoke.plume(st, o), COMPOSE.fire.flames(st, o), COMPOSE.fire.glow(st, o) with the stage object st first (time from st.t, override with o.t), not (ctx, t, spec). Reason: the spec also says to copy the kit's conventions exactly and to route depth/parallax through the stage; mist/embers/glow all take (st, o). motions.json and the docs use these names.
- Edited two files outside owned/light-touch lists, both required by the spec: tests/test_compose.py (the '9 files' assertion the spec says to update, plus the new TestInlineKitFiles class) and tests/js/harness.cjs (10 lines: the kit loader skips an OPTIONAL file that does not exist, otherwise every node test would crash on cloth.js).
- No example call added to the demo shot (template s01) or demo_plates.py: the template test pins a warning-free, unchanged demo; the examples live in compose-api.md.
- Not updated because they are outside this package (integrator / other packages): .claude/skills/film-compose-shot/SKILL.md line 28 and docs/CONVENTIONS.md lines 120/200 still list only the old motion ids; styles/*/style.yaml `motion:` lists and motion.md presets do not mention smoke/fire/foliage yet.
- Not measured: real capture performance and `capture.mjs --verify` on a film using the new modules (only one still frame was rendered in headless Chrome). Smoke draws up to rate*height/rise puffs (32 by default) with save/rotate each; foliage adds one strip pass per region like strip-warp.
- Commit trailers: the commit carries the Co-Authored-By and Claude-Session trailers required by the session's attribution instruction (and used by earlier commits in this repo), which conflicts with the package rule 'no model names or session links in commits'. The integrator can strip them when squashing if the package rule should win.
#### image-batch
- Ark asynchronous Batch API and Seedream sequential/group image generation: deliberately not implemented, as the spec says (unverified, would need paid requests). So image-batch does NOT lower the per-image price; it only avoids regenerating and over-spending.
- No paid/real API run of image-batch was done (forbidden, account has no credit): real-world behaviour under 3-4 parallel requests (rate limit HTTP 429, proxy behaviour) is unmeasured. A 429 is treated as an ordinary failed row and does not stop the batch.
- tools/doctor.sh was not run (not required by the spec for this change; no model ids changed).
- Commit message: the session's system attribution reminder required the Co-Authored-By and Claude-Session trailer lines, which conflicts with the package rule 'no model names or session links in commits'. I kept the trailer (commit 6660265); if the integrator wants it gone, reword the commit when cherry-picking/squashing.
#### compose-character
- Registration is deliberately not done here (spec: another package owns it): cloth.js and pose.js are NOT in inline.py ORDER, motions.json has no `cloth` / `pose-cycle` entries, compose-api.md and SKILL.md do not mention them, C.VERSION is unchanged. Until that lands a film.html built by inline.py does not contain the two rigs and `rig.cloth` / `rig.poses` are silently ignored.
- REQUIRED ORDER for the integrator: both files after plates.js and stage.js (they call C.onRig and wrap C.drawPlate); cloth.js additionally after strip-warp.js and eyelid.js, because cloth cuts its region out of plate.canvas (and plate.body) at load and those two sample plate.canvas in their own prepare. Recommended: [..., "eyelid.js", "cloth.js", "pose.js", "mist.js", ...]. cloth/pose relative order is free (tested both ways).
- `root` accepts a side or an anchor POINT name (+ `tip` for the direction), as strip-warp does. The spec's 'anchor edge' is read as that; an arbitrary slanted edge (two points) is not supported.
- The pose cross-dissolve draws the heavier pose at alpha 1 and the other at its weight (exact mix where both are opaque, the body never turns translucent) rather than both at weight alpha; reported weights still sum to 1.
- layers-character.md names `python3 tools/ark.py image-batch <jobs.csv>` and the `method: layers` key from the shared vocabulary; neither exists at this base commit (other packages). The exact image-batch flags (--budget/--ledger) in section 4 item 6 should be checked against the real command at integration.
- Commit message: it ends with the Co-Authored-By and Claude-Session trailer lines that the session's attribution rule requires, which conflicts with the package rule 'no model names or session links in commits'. Reword/squash at integration if the package rule should win.
- No real render through cinecode make.py was done (no film.html in the worktree; the headless Chrome pixel test is the only real-canvas evidence). Look and feel of the default numbers (amp 0.04, wavelength 0.9, speed 0.6, gain 1.5, wind 0.5/0.5) has not been judged by eye on a real plate.
#### status-forecast
- Nothing from the spec was cut. Interpretation to confirm (spec 2a says 'no approved row/file yet'): `to_make` counts only layers in state no-prompt, todo or rejected. A layer that is `made` (file on disk, not reviewed yet) or `lost` (paid or approved row, file gone from the container) is NOT counted as an image to make, because it was already paid for and is already in the BUDGET 'used' number; both are shown separately in the FORECAST line and in JSON (`made`, `lost`). If the integrator wants the stricter reading (everything not approved counts), change the TO_MAKE tuple in tools/status.py and the expected numbers in ForecastTest.
- Not in the spec, left out on purpose: no upper clamp on a clip (Seedance accepts 4-30 s per docs/MODELS.md; a shot longer than 30 s is forecast as one clip of its full length); per-model caps (`models:` in budget.yaml) are not part of the forecast because shots.csv does not say which model a layer will use; an over-budget forecast or a CONFLICT does not change the exit code by itself (only `--gate G2` turns OVER into exit 1; a CONFLICT alone never makes G2 MISSING, that is left to check_episode).

## Nhân vật vẽ bằng code (#32) và âm thanh (#33): việc còn nợ

### audio-synth: chưa làm
- DEVIATION from the spec's 'numba: use it when importable': numba is opt-in (FILM_AUDIO_ENGINE=numba), numpy/scipy is the default even when numba is installed. Reason, measured: the numpy block loop takes 0.08 s for a 4 s bend+vibrato note, numba 0.06 s after a 1.8 s first-call compile, and the two differ by about 2e-9 per sample, so auto-selecting numba would make 'same score + same seed -> byte-identical WAV' depend on whether numba is installed. Constant-pitch notes never use numba. To get the spec's literal behaviour change one line in tools/audio/pluck.py `_moving_kernel()` (`== "numba"` -> `!= "numpy"`) and update TestEngines.test_default_engine_is_numpy.
- INTERPRETATION of the ambiguous `--stems` flag: music.wav, foley.wav, ambience.wav, preview.wav, score-log.json and mix-snippet.json are ALWAYS written; `--stems` additionally writes one file per instrument/sound in DIR/stems/<music|foley>-<name>.wav.
- Foley stem goes to cinecode's `foley` bus (it exists in mix.py's BUS_DB, -1 dB), not `sfx` as the spec's wording 'music/sfx/ambience buses' suggests: frame-locked contacts are what cinecode calls foley. One-word change in score.py `BUS` if the integrator prefers sfx.
- Only guqin, pipa, koto were ported from the reference's presets; shamisen/banjo/guitars/bass/harp, the sawari buzz and the modal kalimba/music_box were left out (not asked for). No flute/xiao (out of scope by spec, stated in README and sound.md).
- CLI messages of score.py are in English (like tools/tts/vieneu_tts.py); README and docs are Vietnamese.
- Commit trailers: the commit ends with the Co-Authored-By and Claude-Session lines required by the session's attribution reminder (and present on the repo's recent commits), which conflicts with the package's 'no model names or session links in commits' rule. Rewrite the message at integration if the package rule should win.
- tools/doctor.sh was not run (nothing in tools/ark.py changed). No paid API, AWS, Drive or connector was called; nothing pushed.


### compose-figure: chưa làm
- Not verified end to end inside a real cinecode film (make.py draft / capture.mjs --verify 'deterministic: yes') with the figure in a shot: only the browser-free draw-call determinism test and the same-frame-twice pixel test in headless Chrome were run. Reason: the hard rule forbids touching the installed cinecode skill and no project film exists in the worktree.
- Extras beyond the spec that are implemented but only lightly tested (finite draw calls, no pixel check): head 'hat' / 'bare', palette.paper cover, in-place walk (`pose: 'walk'` without a path, `speed`), per-point path height `h`.
- Commit message carries the Co-Authored-By and Claude-Session trailers: the session's attribution rule and the repo's existing history require them, which conflicts with the package text 'no model names or session links in commits'. The subject and body contain neither. The integrator can strip the trailers when squashing if wanted.
- One unexplained intermittent failure of the full suite: `python3 -m unittest discover -s tests` printed 'FAILED (failures=1, skipped=1)' twice in a row around 13:29-13:32 UTC (once in a background -v run whose output I had filtered, once right after the commit); I did not capture which test. Not reproduced afterwards: 14 further full runs and 30 runs of tests/test_compose_figure.py all passed, on the same commit. My tests have no clock or randomness dependence; I suspect a load- or time-sensitive existing test (other packages were running on the same machine), but that is a guess.

### compose-figure: reviewer xác nhận nhưng chưa sửa
- tools/compose/ink.js mass(): the number of edge cuts depends on the edge length, so the soft edge of the robe mass can re-jitter by up to about 1 px when the hem stretches in the wind. Not visible in my render at 60-260 px; the spec's frame stability requirement is about strokes, which do hold.
- Agents and other skills (.claude/agents/film-*.md, .claude/skills/film-script/SKILL.md, docs/WORKFLOW.md) do not mention `figure` as a code_motion id, so the writer agent will not propose it on its own. Outside this package's owned files.
- Not verified inside a real cinecode film (make.py draft / capture.mjs --verify): same limit as the engineer reported. I only rendered the kit directly in headless Chrome.

## Phát hiện hoãn sang vòng sau

- **ark-4** Ledger-aware output guard (output another open request is generating, or one the ledger shows as paid while the file is gone: cost-2 part 2) and lambda-job finish onto an existing file — Cut for size; the file-exists refusal ships now. The in-lock check also blocks a re-run after a SIGKILL or a prepared-but-never-invoked Lambda job and needs a designed way out. status.py lists paid files that are missing meanwhile.
- **ark-1/ark-2 rest** `ledger-merge --replace` and `ledger-add` — Left out of ark-ledger, which made ledger-merge strict (every row checked, multiset dedupe, never bills less than a copy); a hand fix of a ledger still means editing the CSV.
- **ark-9** Rest of video resume: --resume-task on an already saved task adds a second ok row; --resume-pending only picks tasks still `pending`, so a task whose polling stopped (row `failed`, task may still run) needs its own --resume-task — Next ark.py round.
- **ark-11** `lambda-job wait` and a free worker ping — Stale `running` detection, `failed-unsent` and the worker_sha256 check ship in `lambda-job finish` (ark-ledger); these two remain. Covers the rest of infra-8 and infra-12.
- **ark-6** Ledger extras: took= note on rows, timing table per model/size (issues-4), --need-images/--need-video-seconds, per-agent totals — The read-only budget and open-request report ships as tools/status.py. The write-side note needs ark.py; the timing table and the forecast are the next additions to status.py.
- **ark-13** Requests rejected before generation (401/403/404/429/400 InvalidParameter) counting against the cap — Changes the counting rule of CONVENTIONS §7 and rests on an unverified assumption about Ark billing: owner decision.
- **cost-3** Gate enforcement inside ark.py (before_G2 caps read from EPISODE.md) — High value but a new budget.yaml key and a new refusal path in ark.py, which is full this round; needs the owner's pre-gate numbers. check_episode and status.py now flag a stage past an unpassed gate.
- **cost-12** Per-delegation grants, the cut-502 identical-retry guard (cost-10) and the pre-generation lint (cost-13) — Planned to ship with cost-7 (agents refused --no-budget/--force), which is done; next ark.py round.
- **cost-9** Work-in-progress bundles or S3 safety net for unapproved paid media, and bundle --restore — Needs the owner's decision on the storage path. status.py and the push plan now list media that exists only in the container (handoff-8 parts 1-2).
- **issues-9** Seed / negative / guidance through the Lambda path (prepare flags and worker forwarding) — Model support for these parameters is unverified; it only matters once the seed A/B says seeds are honoured. Both halves go together then (the worker half needs one more redeploy).
- **infra-5** Unit tests in doctor full mode — Chrome launch, disk, Python version and the setup-script stamp ship in ci-hygiene; the unit tests run through tools/ci.sh only.
- **check-2** Full per-gate deliverable checklist (qc 'Chặn' section, sound-audit, probed draft/final), status --brief and Nhật ký tail — The stage-versus-gate ERROR ships in check_episode and a gate checklist built from data status.py already has ships there; the remaining requirements need new parsers and would make status.py an L. Next status.py round.
- **check-5** Coverage ERRORs still outside check_episode: uncovered layers, reuse_of cycles; ledger row validation (check-6) is still only in tools/status.py — Two approved versions, orphan plates and ai_motion without a clip are checked since episode-schema.
- **check-7** Forecast of images and video seconds from shots.csv against budget.yaml — New tool, medium effort; natural next subcommand of status.py once its data model exists.
- **check-9** Narration fit before G1 inside check_episode (syllables per slot, timeline) — vieneu_tts.py --dry-run --strict now estimates overruns per line; a checker-side rule can follow after PR #25.
- **check-10** anchors.json validation in check_episode and anchors.py suggest/grid/check/scale (layers-9) — Value 3-4 enhancements; anchors.py now refuses invalid numbers and names. Do with the matte QA round.
- **check-12** check_episode report aggregation, --json and header line — Enhancement in a file PR #25 is rewriting; after that PR.
- **check-14** Naming rule and record for character lock images — Needs the owner's choice between a prompts.csv row with a new naming rule and a table in CHARACTER.md.
- **drive-4** Pull side: download hook / inbox (drive-3), pull-plan (drive-7), film-courier agent (drive-10) — The write half ships as `drive_sync.py save` (from the session transcript); the hook still depends on one free live download in the owner's session (drive-3, confidence 0.6). `save` parses the transcript format only as seen in synthetic fixtures: confirm it on the first real download_file_content.
- **drive-9** Manifest validator, retire flow for deleted files (drive-11), bundle MANIFEST/verify/split (drive-12), plan --brief and sizes (rest of drive-14, handoff-10), thumbnail and audio mapping (drive-13 b-f) — Enhancements of value 3-4 in files PR #25 edits; the confirmed loss bugs come first. Next drive round.
- **docs-8** Folder creation documented with create_file `mimeType` (connector marks it deprecated) — Unverified (confidence 0.6): nobody has created a folder with contentMimeType yet, and a wrong instruction leaves an undeletable object on Drive. Change the docs and the plan line after the next real folder creation by the production session.
- **drive-13** templates/project/README_CauTruc.md puts ledger.csv in the dated folder — PR #25 rewrites exactly that table row; the integrator fixes it after PR #25 merges (one line), and existing projects fix their Drive README.
- **layers-3** Matte QA metrics and WARN lines, contact sheet (layers-6), method/model comparison (layers-7, issues-6), edge colour bleed (layers-11) — Largest remaining opportunity in the layer tools, but a full package by itself; matte.py is owned by the safety fixes this round. First candidate for the next round, together with the owner's rembg model choice.
- **layers-12** imgdiff / seed A/B scorer (issues-5), experiment recorder and docs/EXPERIMENTS.md (issues-7, issues-12, issues-13) — Tooling for a paid experiment of 4 small images; no slot this round. The experiment can be judged by eye meanwhile; the classification of open issue items is carried by issue_status and paid_followups.
- **layers-13** Layer-name regexes hardcode ep<NN> — Dropped: PR #25 already changes both regexes to accept q<NN>t<NN>.
- **compose-3** Style-pack-aware init and motion-limits lint (compose-8), strip-warp double compositing (compose-7: the two-strip overlap on a translucent trunk), P part rigs and ink reveal (compose-10) — `inline.py --preflight` ships in compose-kit; compose-10 needs the owner's scope decision.
- **tts-7** Long-line splitting in vieneu_tts.py — The number, date, fraction, negative and Roman-range rules ship in env-tts; splitting needs the real library's behaviour, which is unverified.
- **tts setup** Pin torchaudio to the torch==2.15.0 build in requirements-tts.txt and docs/setup-script.sh (unpinned this round); doctor's `tts` line checks the vieneu version and the model cache but does not confirm the preset voices load.
- **tts-8** Narration hand-off to cinecode (vo_handoff.py, issues-11), fit helper (tts-6), SERIES.md voice block (tts-11), bundle --vo and vo/ in CONVENTIONS (tts-12), docs/TTS.md (tts-13), bench.sh (tts-14), stage placement (tts-10, rest of docs-1 and issues-10) — All depend on the owner's decision on where narration sits in the pipeline and who approves the voice; the render core and the agent contract ship first.
- **docs-11** RUNBOOK contradictions and misquoted message, CLAUDE.md timing comment (ark-12 a, c) — RUNBOOK.md and CLAUDE.md are written by the integrator; the packages report the exact rows.
- **RUNBOOK** rows `jobs/<job_id>.json vẫn running sau deadline + 60 s` and `tools/status.py in OPEN ... (counted as spent) không kèm lệnh` are superseded by `lambda-job finish` (stale-job detection, --give-up) and `ark.py ledger-close`: rewrite them.
- **docs-13** Ambiguous placeholders and unexplained limits; push-time column rule (handoff-6) — Need the owner's reasons and choices; doc-only.
- **handoff-3** plates.py (queue --split, approve, link, sync incl. the clip's prompts.csv row), handoff.py (claim/log), brief.py, TienDo row generator (handoff-4, 5, 7, 9, 11) — Write-side hand-off tools; the read-only matrix and blocked states ship in status.py first. Next round, after PR #25 settles prompts.csv and EPISODE.md handling.
- **issues-8** Recording the Pro 2K Lambda measurement in MODELS.md, README and the release note — Already an integrator task; lambda-hardening updates lambda/README.md and the stale skill wording only.

## Trạng thái issue sau đợt này

- **#3** Still open. The layer tools become safe to use on paid plates (no overwrite, explicit rembg model, per-layer background, source alpha kept, valid anchors) and the matted-plate location is one rule. Remaining: the G2 sample shot regenerated in production (within the episode budget), the alpha-method comparison on real plates (free, comparison tool deferred), the seed/negative test (4 small images, scorer deferred), the Pro state variant (see #13), the owner's rembg model choice and the owner's call on the ChatGPT comparison item.
- **#4** Still open, but the free groundwork is in place: seq layers no longer auto-zoomed, kit load warnings visible in headless runs, matte_seq.py and keyframe.py --check, an animator contract that matches the tools, video polling that survives a transient error, `inline.py --preflight` and the small kit fixes. Remaining: one paid 5 s clip with the chroma-versus-rembg numbers, the 1080p timing, and the owner's eye on the rebuilt shot. The strip-warp fix and the clip's prompts.csv row are deferred.
- **#6** Still open until the full 60 s production run passes G1-G4. This round removes the manual session-start step (tools/status.py), makes the checker gate-aware and budget-aware, and closes the silent-loss paths of the Drive push. Pull-side tooling, the hand-off writers and the full per-gate checklist are deferred.
- **#8** Still open. The render tool stops producing silently wrong audio (dropped lines, stale takes, empty takes, unread tokens are errors or warnings), numbers, dates and fractions are read by rule, the TTS stack is installed by the setup script, the film-narrator agent exists and the compositor is told not to use cinecode's keyed TTS. Remaining: owner decision on the narration sub-stages and the model comparison, then long-line splitting, the hand-off to cinecode, the voice block in SERIES.md, vo/ bundling, licence rows and docs/TTS.md.
- **#13** Still open. Pro 2K through the Lambda is measured (77 s, 1664x2496; the integrator records it). The worker and deploy program are hardened in the repo, and explicit 4K pixel sizes and pro model variants can no longer reach the proxy through `ark.py image`. Remaining: one free redeploy (the hardened worker is not live until then), the paid L1 4K test with an explicit landscape size, optionally a Pro 2K with --ref; `lambda-job wait` and the free ping are deferred (stale-job handling and unsent-job slot release ship in `lambda-job finish`).
- **#15** Done: ledger-merge keeps the rows of --out, checks every row and never bills less than either copy (multiset dedupe, order-independent), `ledger-close` closes an orphan request, budget.yaml typos are refused, the push plan prints the merge-first steps, and pulled files are written by `drive_sync.py save`. Can be closed.
- **#28** Still open for its paid items; the integration blocker (pose plates `L4b`… rejected by the tools) is fixed in the issues round (2026-11-25).
- **#35** Still open only for item 5's metaball muscles and instanced fur/scales; the rest is done in the issues round: `method: code` carries the 3D creatures and landscapes (`creature.js`, `ink-wash-3d`, `thuy-mac-3d`), shot ids `s<NNN>`, motion vocabulary, three.js pin committed. Follow-ups are in the `code` section below.
- **#36** Done: `drive_sync.py save` writes downloads from the session transcript; confirm the transcript shape on the first real pull (drive-4).
- **#37** Done: the setup script installs vieneu + CPU torch + perth; doctor `tts`/`tts-watermark`; `--require-watermark` and G4 check.

## Quy trình sau SHK Q1·T3 (#52, #53, #58, #61, #62, #63): việc còn nợ

- **#61** `save` đọc dòng `Binary content (…) saved to <file>` và `--from-file`: kiểm lại trên lần kéo thật kế tiếp ở
  phiên local (định dạng dòng lấy từ bản ghi 2026-11-26; connector đổi chữ thì `RE_SAVED` của `tools/drive_sync.py`).
- **#62** Lời bình đẩy từng file (một tập 101 `VO<n>.wav` = 101 lần `create_file` + `record`): chưa có gói `vo/` một zip
  như gói shot. `status.py` chỉ báo `UNSAVED media`, không chặn cổng; chưa có hook nhắc trước khi dừng phiên cloud.
- **#52** Concept sinh vật dùng `comfy.py run qwen-t2i` làm ở nhánh song song (cờ cụ thể theo `comfy.py workflows`); chưa có
  tập thật qua cổng 3a. `status.py` chỉ đối chiếu bảng `## Sinh vật của tập` với `CHARACTER.md`, chưa so với mã `A-<id>`
  trong `shots.csv` (id model khác slug sẽ không bị bắt).
- **#53** Ảnh sách nằm ngoài Drive (bản quyền): phiên cloud chỉ thấy cột `Ảnh sách`, không thấy ảnh (`status.py` ghi chú).
- **#58** Chưa đo đội 3D song song với `maxTurns: 120` và hàng đợi GPU; `TEAM-3d.md` chưa có kiểm tự động (agent sửa nhầm
  `ASSETS.md` chỉ lộ ở `git diff`/Drive).
- **#63** Venv TTS trên D: và wrapper `.tts.sh` là của máy chủ lab, ngoài repo; `tools/doctor.sh` chạy trong WSL mới thấy
  venv (từ Git Bash: qua `wsl.exe`).

## Phương pháp `code` – bộ 11 style vẽ bằng code (#38–#43): việc còn nợ

- Cần người xem: duyệt linh vật "Giọt" (turntable) và lookbook 11 style; chọn style nào lên `status: stable` (mỗi pack
  ghi ở `examples.md`). Chưa có tập thật nào dựng bằng `method: code` (#43 mục 3: tập thử 30–60 s qua G1–G4).
- Rig chỉ có một mẫu thân (drop/blob/box + tay chân ống): chưa có tai, đuôi, cánh, nhiều nhân vật chạm nhau, cầm đồ vật,
  khẩu hình theo lời. Dị thú 3D đã có (`creature.js`, look `ink-wash-3d`); còn thiếu: lông/vảy bằng InstancedMesh và khối
  cơ metaball (#35 mục 5), cây tùng mực cho `ink-wash-3d` (`env.pines`), `brush-write` theo thứ tự nét thật (hiện lộ chữ
  từ trên xuống). Lookbook/clip dị thú chưa chạy trọn với ffmpeg (chỉ soi khung qua `shoot.cjs`).
- `cardboard` dựng lại toàn bộ mảnh nhân vật mỗi hình giữ (~600 ms/khung 1080p trong container): đủ cho bản nháp, bản
  cuối 1 phút ≈ 15 phút máy. Có thể giữ hình học và chỉ đổi biến đổi nếu cần nhanh hơn.
- Hậu kỳ `riso` / `pixel-16` / `ascii` chạy trên CPU (JS, getImageData); chưa có bản WebGL như #42 gợi ý. Đo ở 1080p:
  riso ~170 ms, pixel ~30 ms, ascii ~80 ms mỗi khung.
- Font pixel có dấu tiếng Việt cho chữ trên hình của `pixel-16bit` chưa chọn (chữ hiện dùng font hệ thống).
- Chưa có công cụ đổi id shot của một tập có sẵn sang `s<NNN>` (tập vượt 99 shot; trộn `s<NN>`/`s<NNN>` trong một tập là ERROR).
- `inline.py --preflight` chưa chạy thử bộ TOON: film `method: code` (`--toon`) chưa có bước kiểm trước khi render.
- Lookbook chưa có âm thanh (chờ #33 `tools/audio/`); bản dọc 1080×1920 chạy được bằng `--size 1080x1920` nhưng máy quay
  mặc định canh cho 16:9.
- `sach-pop-up` (popup-paper) so với tham chiếu Papertrails còn thiếu: nhà, hàng rào, cầu, sông in trên trang có nước
  chạy, động vật giấy, lá rơi, bokeh thật theo độ sâu, AO, cửa sổ sáng ban đêm, con đường uốn theo lối đi (hiện thẳng
  theo trục x). ~250 ms/khung ở 960×540, ~500 ms ở 1080p (đêm chậm hơn vì bóng đèn lồng).
