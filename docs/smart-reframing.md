# Smart reframing (Milestone 7)

PeakSift detects and tracks visible faces to generate a smooth vertical crop path, with centre and manual fallbacks. A generated clip (any aspect ratio) becomes a 9:16 short whose crop follows the most prominent face. When no face is clear, the crop stays centred, and the creator can always pin the crop to a focal point by hand instead.

## What it does, and does not do

| Does | Does not |
| --- | --- |
| Finds faces in frames sampled from the clip (local CPU detector) | Identify people, recognise faces or know who is speaking |
| Links detections over time into face tracks and chooses one subject (or a close pair) to follow, with hysteresis | Use audio, lip movement or diarization ("active speaker detection") |
| Plans a smooth, speed-limited crop path that keeps that face inside the frame | Track bodies, pets, products or any other object |
| Cuts with the shot when one face vanishes and another appears elsewhere | Understand scenes, zoom dynamically, or make split-screen layouts |
| Falls back to a centred crop when nobody is visible, and offers a manual focal point | Offer a keyframe timeline or crop-animation editor |
| Renders the moving crop with FFmpeg, with captions fixed on screen | Need a GPU, a cloud service or a network connection at run time |

## Architecture

```
Editor ──POST …/clips/{clip_id}/reframe──▶ API ──(analysis id)──▶ Redis ──▶ Celery worker
                                                                            │
   clip.mp4 ─▶ ffprobe (display geometry) ─▶ FFmpeg pipe (rgb24, N fps, scaled) ─▶ face detector
                                                                            │
                         detections ─▶ tracking (tracks + subject) ─▶ crop path planner
                                                                            │
                     reframe_keyframes + statistics + "completed"  (one transaction)

Editor ──POST …/clips/{clip_id}/edits {layout: smart_reframe, reframe_analysis_id}──▶ edit worker
   persisted keyframes ─▶ re-validated ─▶ FFmpeg crop(x(t), y(t)) → scale 1080×1920 → captions
```

| Piece | Where |
| --- | --- |
| Data model (`reframe_analyses`, `reframe_keyframes`) | `backend/app/models/reframe.py` |
| Configuration snapshot and fingerprint | `backend/app/services/reframe/config.py` |
| Frame sampling | `backend/app/services/reframe/sampling.py` |
| Detector contract | `backend/app/services/reframe/detection.py` |
| YuNet face detector | `backend/app/services/reframe/yunet.py` |
| Tracking and subject selection | `backend/app/services/reframe/tracking.py` |
| Crop path planning | `backend/app/services/reframe/path.py` |
| Background analysis | `backend/app/services/reframe/pipeline.py`, `app/workers/reframe_tasks.py` (`peaksift.analyze_reframe`) |
| API | `backend/app/api/reframe.py` |
| Rendering the moving crop | `backend/app/services/clip_edit/smart_crop.py`, `composition.py` |
| Editor | `frontend/components/app/editor/smart-reframe.tsx`, `preview-stage.tsx`, `frontend/lib/reframe.ts` |

**Coordinates.** Every position and size is a fraction of the *display-oriented* source frame: rotation metadata is already applied, `x` grows to the right and `y` grows downwards, and both run from 0 to 1. Sampling, detection, tracking, the stored keyframes, the API, the browser preview and the renderer all use this convention.

## Detector: provider contract and default

`SubjectDetectionProvider` is a small protocol: `name`, `version`, `detect(frame) -> list[SubjectDetection]`. A detection has a clip-local timestamp, a type (`face`), a confidence in [0, 1] and a normalized box. `normalize_detection()` drops untrustworthy output:

- NaN and infinity;
- confidences outside [0, 1];
- negative timestamps;
- zero or absurd sizes;
- boxes that are less than 30 % visible.

A face cut by the frame edge is kept and clamped. `strongest()` caps a frame at 32 detections, in a deterministic order.

Three outcomes are deliberately distinct:

- **Faces found:** a list of detections.
- **No face:** an empty list. This is a valid result and leads to centre fallback.
- **Detector broken:** `DetectorUnavailable` (unknown detector, model missing or not the pinned file, runtime missing) or `DetectorFailure` (an exception on a frame). The analysis **fails** with `detector_unavailable` or `detector_failed`. A broken detector is never reported as "no face found".

### Default: YuNet on onnxruntime

The default detector is `REFRAME_DETECTOR=yunet_face`, OpenCV Zoo's `face_detection_yunet_2023mar`:

- **Model:** 640 × 640 letterboxed BGR input, strides 8/16/32, `score = sqrt(cls × obj)`, NMS at IoU 0.3. It is decoded like OpenCV's `FaceDetectorYN`.
- **Lifecycle:** the ONNX session is created lazily on the first frame and reused by the worker process. Importing the app or the worker loads nothing, and a test pins this.
- **Licensing:** the weights are MIT (© 2020 Shiqi Yu). `onnxruntime` is MIT and was already installed as a faster-whisper dependency, so no new package was added.
- **Installation:** the operator installs the model once with `python scripts/fetch_reframe_model.py`. The script downloads from a pinned URL, checks the pinned sha256 and writes the file atomically to `REFRAME_MODEL_PATH` (default `./models/face_detection_yunet_2023mar.onnx`, git-ignored). PeakSift never downloads a model by itself: not at import, not at startup, not in tests and not in CI. The detector refuses any file whose sha256 differs, and CI fails if any model weights are tracked in Git.
- **Readiness:** `POST …/reframe` answers `409 "Smart framing is not available on this server"` until the pinned model is installed.

**Why not MediaPipe (evaluated first).** These findings were checked in this environment:

- MediaPipe 1.1.0 is Apache-2.0 and has a Python 3.12 arm64 wheel. However, it bundles no face model (no `.tflite`; the legacy `solutions` API is gone), so the Tasks `FaceDetector` needs the same kind of model provisioning.
- It pulls heavy dependencies: `opencv-contrib-python` (55.7 MB), `matplotlib`, and `sounddevice`, which needs PortAudio on Linux. Its installation stalled twice here.
- Its short-range BlazeFace model resizes the whole frame to 128 × 128 and is designed for selfie-distance faces. That is a poor fit for landscape creator footage, where faces are small.

The provider contract is detector-independent, so another detector can be added behind it without touching tracking, planning or rendering.

**Real-detector evidence.** The opt-in test (`PEAKSIFT_REAL_DETECTOR=1 REFRAME_TEST_FACE_IMAGE=<photo>`) and the milestone acceptance run real YuNet inference. During development, the public-domain NASA astronaut portrait from scikit-image (not committed) gave these results:

| Scene | Confidence |
| --- | --- |
| Composited into a 1080p landscape | 0.93 (7.6 ms per frame on an Apple-silicon CPU) |
| Face only 2.5 % of the frame width | 0.84 |
| Face cut by the right edge | 0.94 |
| Portrait frame | 0.94 |
| Blank frame | no detections |

CI runs the decoder against a fake ONNX session. It never runs real inference and never downloads a photo.

## Sampling

`probe_geometry()` reads the display-oriented size and duration with ffprobe. `sample_frames()` then streams frames from **one FFmpeg process** through a pipe:

- The filter is `fps=N:round=up`, then scaling to `REFRAME_ANALYSIS_WIDTH` (default 640, never upscaled), then `rgb24` output.
- The default rate is `REFRAME_SAMPLE_FPS=2`. FFmpeg applies the rotation itself, and audio and variable frame rate do not matter.
- Frames come back as `SampledFrame(index, timestamp, width, height, rgb)` with timestamps `i / N`. FFmpeg's default rounding (`round=near`) was measured to deliver frames about 0.2 s late at 2 fps; `round=up` makes frame `i` the first source frame at or after `i / N`. A test compares sampled frames against direct seeks.
- **No temporary files:** nothing is written to disk.
- **Timeouts:** a watchdog kills FFmpeg at `REFRAME_SAMPLING_TIMEOUT_SECONDS`, even if a pipe read is blocked.
- **Clean stops:** stopping early (an error, a takeover) closes the stream and kills FFmpeg at once.
- **Errors:** they are short codes with path-free messages: `source_missing`, `source_unreadable`, `sampling_failed`, `sampling_timeout` and `ffmpeg_missing`.

## Tracking and subject selection

`track_subjects()` is small and deterministic. Creator footage has a handful of faces, so no tracking framework or SciPy is needed.

### Association (frame by frame)

- **Prediction:** each live track predicts its box from its last two observations. The prediction assumes constant velocity, capped at 2 frame-widths per second.
- **Matching rule:** a track and a detection match if the boxes overlap (IoU ≥ 0.1). They also match if the centre moved at most 1.5 face-widths × √(gap in samples) and the sizes are similar (area ratio ≥ 0.4).
- **Assignment:** pairs are taken greedily by cost (`distance − IoU`), one to one. Ties are broken by track id, then by position.
- **New and ended tracks:** an unmatched detection starts a new track. A track not seen for longer than `REFRAME_MAX_GAP_SECONDS` (1.5 s) stops matching.

### Positions between observations

- **Inside a gap:** a track's position is interpolated between observations.
- **After its last observation:** the position is held with confidence decaying linearly to zero over `max_gap`, so one missed detection never moves the crop.
- **Steering:** a track needs at least two observations to steer, which filters single-frame false positives.

### Choosing the subject

- **Score:** each visible track scores `0.45·size + 0.30·persistence + 0.15·confidence + 0.10·centrality`.
  - size is relative to the largest visible face;
  - persistence is the observed duration, up to 3 s;
  - centrality is closeness to the horizontal centre.
- **Switching:** the current subject stays until it disappears, or until another track has outscored it by 25 % continuously for 1 s. Exact ties go to the leftmost face, so the result does not depend on detector output order.
- **Hand-offs (shot changes):** a hand-off happens when the followed face has ended (only held past its last observation) and a face that first appeared *after* that observation is visible. The new face takes over immediately, and the sample is flagged `cut`. Faces that were on screen together never produce a hand-off.

This is not speaker detection. "The subject" means the most prominent, persistent visible face.

## Crop geometry

The crop has a fixed size; there is no zoom in V0.7.

| Source | Crop (fractions) | Moves along |
| --- | --- | --- |
| Wider than 9:16 (landscape, square) | full height, width `H·9/16 / W` | x |
| Taller than 9:16 | full width, height `W·16/9 / H` | y |
| Exactly 9:16 | the whole frame | nothing |

## Crop path planning

`plan_crop_path()` simulates a virtual camera every 0.1 s:

1. **Target and dead zone.** The target keeps the subject's centre within `REFRAME_DEAD_ZONE` (0.10 crop widths) of the current crop centre. A face drifting inside that zone moves nothing; a face leaving it is followed by the minimum movement.
2. **Face margin.** The whole face box keeps `REFRAME_FACE_MARGIN` (0.12 crop widths) from both crop edges. A face larger than the usable area is simply centred.
3. **Group framing.** A second face at least 60 % of the primary's size, which fits inside the crop together with the primary (margins included), is framed with it, centred on the pair. Entering or leaving group framing needs 1 s of stable evidence. Faces too far apart keep the primary; there is no split screen.
4. **Look-ahead.** The path is computed offline, so the target is read `REFRAME_SMOOTHING_SECONDS` (0.5 s) ahead, which cancels the smoothing lag.
5. **Smoothing.** Exponential, with that time constant. It never overshoots, and it settles exactly once within 1e-4.
6. **Pan limit.** The centre moves at most `REFRAME_MAX_PAN_PER_SECOND` (0.35 of the frame axis per second). A detector jump can never become a teleport.
7. **Bounds.** The centre is clamped so the crop never leaves the source.
8. **Fallback.** With no subject, the target is the centre (mode `fallback`).
9. **Shot changes.** At a hand-off whose new position is more than 25 % of the crop away, the camera **cuts**:
   - Two keyframes 1 ms apart are placed halfway between the old subject's last sample and the new subject's first. The framing therefore switches within half a sample period of the real cut.
   - Smoothing restarts from the new position.
   - The look-ahead never reads across a cut, so the crop neither drifts toward a face that has not appeared yet nor pans slowly across unrelated shots.

   This is a deliberately simple rule, not scene detection. A face entering a continuous shot after nobody was visible still gets a smooth pan.

The dense path is simplified with Douglas–Peucker at 0.002 (about 4 px across 1920 px). Mode changes and both sides of a cut are always kept. A static subject therefore gives a handful of keyframes, not hundreds. The renderer and the browser preview both interpolate linearly between keyframes and hold the first and last values.

## Confidence

The summary describes how much of the clip was framed by a tracked face. It is not a probability of "correct" framing:

- `coverage` is the share of samples with a subject.
- `overall` = `coverage × mean subject confidence / (1 + 0.15 × subject switches)`.

| Level | Rule | Editor copy |
| --- | --- | --- |
| `high` | coverage ≥ 0.8 and overall ≥ 0.6 | **Strong tracking**: a face was followed for most of the clip |
| `mixed` | otherwise | **Some center fallback**: followed in parts, centred where no face was clear |
| `fallback` | coverage < 0.25 | **Manual framing recommended**: no clear face to follow, so the crop stays centred |

The analysis also stores:

- `frames_sampled`, `detections_count` and `tracks_count`;
- `subject_switches` and `fallback_fraction`.

The planner also computes engineering diagnostics: maximum pan speed (cuts excluded), the share of samples whose face lies fully inside the crop, and the number of camera cuts. These are used in tests and acceptance; they are not product claims.

## Manual focal point

The `manual_crop` edit layout takes `focus_x`/`focus_y` in [0, 1], rounded to 3 decimals so slider noise does not create new versions. It renders a fixed 9:16 crop centred on that point, clamped inside the source; on a vertical source the whole frame is used. It needs no analysis. In the editor it is the **Focal point** mode of Smart reframe, the suggested action after a `fallback` result, and the recovery path after a failure.

## Background job

Analysis runs on the existing Celery worker as `peaksift.analyze_reframe`. Only the analysis id crosses Redis. The `reframe_analyses` row is the source of truth.

- **Statuses:** `queued → sampling → detecting → tracking → planning → completed | failed`.
- **Progress:**

  | Stage | Progress |
  | --- | --- |
  | Claimed | 5 |
  | Detection | 10 → 80 (frames analysed ÷ expected frames) |
  | Tracking | 85 |
  | Planning | 92 |
  | Completed | 100 |

- **Attempt fencing:** the task id is committed on the row before the job is enqueued and acts as the attempt token. Every commit and the failure path re-read it, so a stalled worker that a retry took over never writes. A row deleted mid-run stops the job quietly.
- **Atomic result:** the whole path is computed and validated in memory, then the keyframes, statistics and `completed` are written in **one** transaction. `completed` always means a valid path exists, and a failure leaves no partial path.
- **Stale detection:** heartbeats run every `REFRAME_HEARTBEAT_SECONDS`. After `REFRAME_STALE_AFTER_SECONDS` without one, the analysis is reported `is_stale` and can be retried.
- **Retries:** at most `REFRAME_MAX_ATTEMPTS`, on the same row, under a row lock.
- **Deduplication:** every tuning value is server configuration, captured in a versioned snapshot (`algorithm_version = smart_reframe_v1`). `(clip_id, config_fingerprint)` is unique, so pressing **Analyze framing** twice returns the same analysis. A new server configuration creates a new analysis; old ones are kept.

## API

All routes are under `/projects/{project_id}/videos/{video_id}/clips/{clip_id}/reframe` and owner-scoped. Anonymous requests get `401`; another user's resources, or an analysis of another clip, get `404`.

| Method and path | Purpose |
| --- | --- |
| `POST …/reframe` | Start (or return) the analysis for the current configuration. Returns `201` for a new analysis or `200` for an existing one. Returns `409` if the clip is not ready, its file is missing, smart framing is unavailable, or the last analysis failed (use retry). Returns `503` if the queue is down; no row is left behind. |
| `GET …/reframe` | List the clip's analyses, newest first. |
| `GET …/reframe/current` | The analysis for the current configuration, or `404` if there is none yet. |
| `GET …/reframe/{analysis_id}` | Status, progress, staleness, statistics and a safe error. |
| `GET …/reframe/{analysis_id}/path` | The ordered keyframes (`timestamp`, `center_x/y`, `crop_width/height`, `confidence`, `mode`) and the source size. Returns `409` until the analysis is completed. |
| `POST …/reframe/{analysis_id}/retry` | Re-queue a failed or stalled analysis with a fresh attempt token. The number of retries is bounded. |

Responses never contain task ids, worker names, model paths, storage keys, filesystem paths or FFmpeg commands. `provider` is just the detector name (`yunet_face`).

Edits use the existing endpoints, with these additions:

- `POST …/clips/{clip_id}/edits` accepts `layout: "smart_reframe"` together with `reframe_analysis_id`. The id must be a completed analysis of **this** clip, otherwise the response is `409`; another clip's analysis is indistinguishable from a missing one.
- The same endpoint accepts `layout: "manual_crop"` with `focus_x`/`focus_y`.
- Changing caption settings creates a new edit that reuses the same analysis. Framing belongs to the clip, not to the caption style.

## Rendering the moving crop

FFmpeg's `crop` filter evaluates `x` and `y` on every frame, with `t` set to the frame time. `smart_crop.py` compiles the keyframes into a piecewise-linear expression:

- **Validation:** before rendering, the edit pipeline re-reads and re-validates the persisted keyframes (`crop_points_from`). The checks are: finite numbers, strictly increasing non-negative times, a crop of constant size inside the source, and at most `MAX_SEGMENTS` = 1000 segments (longer paths are thinned, keeping both ends). Failures are reported as `invalid_path` or `reframe_unavailable`.
- **Expression shape:** the expression is a **balanced `if(lt(t,T), left, right)` tree**. A flat sum of per-segment terms renders at 50 segments but fails at 100 ("Failed to configure input pad"), whereas a balanced tree is only log₂(n) deep. 1000 segments (a 51 kB expression) were verified on FFmpeg 9.0.2, and CI renders a 1000-segment path on Ubuntu's FFmpeg 6.1 (`scripts/smart_crop_probe.py`).
- **Edges:** values are held before the first and after the last keyframe, then `clip()` keeps the crop inside the frame. The crop size is in even pixels.
- **Filter order:** moving crop → `scale=1080:1920:flags=lanczos,setsar=1` → captions (libass). Captions therefore stay fixed on screen while the framing moves.
- **Output contract:** the same as every short. It is H.264 + AAC, 1080 × 1920 and fast-start, with the source duration and audio if and only if the source has audio. The file is validated with ffprobe and renamed atomically.
- **Untrusted input:** nothing user-supplied reaches the filtergraph. Every value is a finite float formatted by the module.

## Editor workflow

**Smart reframe** is the first layout card. When it is selected, the panel offers **Automatic** or **Focal point**, and shows one of these states:

- **Loading:** "Checking framing analysis".
- **Not analysed:** a short explanation and **Analyze framing**. **Render short** is disabled with the hint "Analyze the framing first, or set a focal point".
- **Running:** "Analyzing framing · *Reading frames / Finding faces / Following the subject / Planning the camera path*", with real progress. Polling runs every 4 s while the analysis is active.
- **Completed:** the confidence copy, plus "*n* face tracks · *x* % centered fallback". A `fallback` result is headed "Framing analyzed" rather than "Smart framing ready", and suggests **Set a focal point instead**.
- **Failed or stalled:** a plain-language reason, **Retry** and **Set focal point**. A detector failure is never shown as "no faces".

**Live preview.** The real clip is positioned inside the 9:16 frame from the completed crop path. It updates on every decoded frame via `requestVideoFrameCallback`, with a `requestAnimationFrame` fallback, and uses the renderer's interpolation. Its own play/seek controls are keyboard-accessible. Without a path, the preview is centred and labelled "Centered until framing is analyzed". The preview is labelled approximate; the rendered MP4 is authoritative.

**Focal-point picker.** It shows the source frame with the 9:16 crop outlined and the outside dimmed. It works by click/tap or drag, with **arrow keys** (Shift for larger steps), or with a slider for the moving axis. It is never pointer-only. State is never shown by colour alone, and the outline animation respects reduced motion.

**Versions** are named by their settings, for example "Smart reframe · Bold captions · Bottom" or "Manual crop · No captions".

## Security

- **Ownership:** every reframe route sits behind the clip ownership chain (User → Project → Video → Clip → Analysis). Missing and foreign resources look identical (`404`), and anonymous requests get `401`.
- **Untrusted requests:** a request can only ask "analyse this clip". The detector, model file and every tuning value are server configuration, and focal points are validated as finite and inside [0, 1].
- **Subprocesses:** ffprobe and FFmpeg run with argument lists and timeouts, never `shell=True`, and their stderr is never stored or returned. Only ids cross Redis.
- **Storage:** clip files resolve only through `LocalMediaStorage.path_for`, which refuses keys outside `MEDIA_ROOT`, including through symlinked directories (regression-tested).
- **Error messages:** stored and returned messages contain no paths, model locations, task ids or commands. The operator hint for a missing model goes to the server log only.
- **Model integrity:** the model file is pinned by sha256, never committed and never fetched automatically.

## Testing

All of the following run in CI. There is no network and no model download, and the detector is faked except for the opt-in real test.

| Area | Tests |
| --- | --- |
| Model, constraints, snapshot and fingerprint | `test_reframe_model.py` |
| Sampling: real FFmpeg (timing vs direct seeks, rotation, portrait/square, VFR, 4K at 60 fps, corrupt or missing input, timeout kill, early stop) | `test_reframe_sampling.py` |
| Detection: contract, normalization, YuNet decoding against a fake session, failure vs no face, lazy loading, pinned model; real YuNet is opt-in | `test_reframe_detection.py` |
| Tracking: association, gaps, crossing faces, glitches, hysteresis, ties, hand-offs | `test_reframe_tracking.py` |
| Planning: geometry, dead zone, jitter, smoothing, pan limit, fallback, groups, edges, cuts, fast movers, leave and return | `test_reframe_path.py` |
| Background job: progress, failures, fencing, takeovers, duplicate delivery, atomic finalize, symlink containment | `test_reframe_pipeline.py` |
| API: 401/404, idempotency, readiness, retry and row lock, queue down | `test_reframe_api.py` |
| Rendering: path validation, expression shape, a real moving-marker render checked frame by frame (1080 × 1920, duration, audio), captions with a moving crop, pipeline and API | `test_smart_reframe_render.py` |
| Manual focal point | `test_manual_crop.py` |

CI also runs:

- `scripts/smart_crop_probe.py`, the deepest allowed path on the runner's FFmpeg;
- the caption probe;
- the live worker smoke, which checks that `peaksift.analyze_reframe` is registered;
- a full Alembic up/down cycle;
- a guard against tracked weights or media.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `REFRAME_DETECTOR` | `yunet_face` | Detector (server-side only) |
| `REFRAME_MODEL_PATH` | `./models/face_detection_yunet_2023mar.onnx` | Pinned model file (install with `scripts/fetch_reframe_model.py`) |
| `REFRAME_SAMPLE_FPS` | `2` | Frames analysed per clip second |
| `REFRAME_ANALYSIS_WIDTH` | `640` | Frames are downscaled to this width for detection |
| `REFRAME_MIN_DETECTION_CONFIDENCE` | `0.5` | Detector score threshold |
| `REFRAME_FACE_MARGIN` | `0.12` | Minimum gap between a framed face and the crop edge, in crop widths |
| `REFRAME_DEAD_ZONE` | `0.10` | Subject drift tolerated before the crop follows, in crop widths |
| `REFRAME_SMOOTHING_SECONDS` | `0.5` | Smoothing time constant (and look-ahead) |
| `REFRAME_MAX_PAN_PER_SECOND` | `0.35` | Crop-centre speed limit, as a fraction of the axis per second |
| `REFRAME_MAX_GAP_SECONDS` | `1.5` | A lost face stops steering after this long |
| `REFRAME_SAMPLING_TIMEOUT_SECONDS` | `600` | Sampling deadline (FFmpeg is killed) |
| `REFRAME_HEARTBEAT_SECONDS` / `REFRAME_STALE_AFTER_SECONDS` | `15` / `900` | Liveness and stale detection |
| `REFRAME_MAX_ATTEMPTS` | `5` | Retries per analysis |

Changing any tuning value changes the configuration fingerprint. The next **Analyze framing** then creates a new analysis, and older ones and the shorts rendered from them stay intact.

## Using it

1. **Upload** a video to a project.
2. **Transcribe** it.
3. **Find clip moments** with AI clip detection.
4. **Generate clip** on a candidate.
5. **Create vertical short** to open the editor.
6. Select **Smart reframe**.
7. **Analyze framing** and wait for "Smart framing ready" (or "Framing analyzed").
8. **Preview** the movement in the 9:16 stage (play or scrub).
9. **Adjust manually if needed:** switch to **Focal point** and click, drag or use the arrow keys.
10. **Configure captions:** style and position. Changing them does not need a new analysis.
11. **Render short.**
12. **Download short.**

Operators install the face model once per server: `cd backend && python scripts/fetch_reframe_model.py`.

## Known limitations (V0.7)

- **Faces only:** tracking is face-first. There is no speaker identification, no active-speaker or audio mapping, and no face recognition or identity. Bodies, pets, products and other objects are not tracked.
- **No editing tools:** there is no dynamic zoom (the crop size is fixed), no split screen, and no manual keyframe timeline or crop-animation editor.
- **Simple cut handling:** shot changes are inferred from one face vanishing as another appears, not from scene analysis. A cut between two shots of the same person at nearly the same position is panned smoothly, and a cut to an empty shot eases to the centre.
- **Small or unusual faces:** faces smaller than about 2.5 % of the frame width, heavily occluded or in profile may be missed. The result is then centre fallback, and manual framing is recommended.
- **CPU only:** analysis and rendering run on CPU (about 8 ms per frame at 2 fps for detection). There is no GPU path, no distributed workers and no cloud rendering.
- **Platform:** storage is the local filesystem only, and there is no publishing.
- **Approximate preview:** the browser preview mirrors the renderer's path semantics but is labelled approximate. Pixel parity was not measured.
