# F1 Telemetry Coach (Marco v4) - Time Trial Edition

Marco is a **Time-Trial-only** live lap engineer for F1 25.

It captures UDP telemetry, builds a fastest-lap reference, compares each lap against that reference in real time, gives concise turn-level coaching, renders lap deltas on the phone UI, and generates a post-session performance report.

## Product Scope (Important)

This app is designed for:

- Solo time trial / hotlapping
- Lap-time improvement
- Corner execution and consistency work

This app is not designed for:

- Race strategy
- Overtake/defend traffic calls
- Pit or tire strategy modeling

## What You Get

### Real-time coaching

- Braking zone and brake-now prompts
- Gear / throttle / speed prompts
- Sector color callouts (purple/green/yellow)
- Corner-specific turn callouts with anti-spam caps

### Lap Perfection analytics

Per corner, Marco tracks:

- Entry speed
- Apex speed
- Exit speed
- Brake point (first significant brake application)
- Throttle re-application point
- Corner segment time
- Corner delta vs reference lap

Corner callouts follow measurable rules and are limited to:

- Max 1 callout per corner per lap
- Max N callouts per lap (`MAX_CORNER_CALLOUTS_PER_LAP`)

### Time loss and mastery

- Top 3 time-loss corners after each lap
- Reason labels (brake earlier, entry speed, apex over-slow, exit speed, etc.)
- Corner mastery score (0-100) + trend

### Compare engine and heatmap

- Current lap vs PB bin-based delta
- Last completed lap vs PB mode
- Track heatmap overlay in phone UI
- Fallback trail rendering if full track outline is not available yet

### Consistency + profile + skills

- Lap sigma (variance over recent laps)
- Sector sigma
- Most consistent / inconsistent corners
- Braking point variance
- Driver profile tags (heuristic): e.g. Aggressive Braker, Cautious Braker, Smooth Throttle
- Skill scores (0-100):
  - Braking Precision
  - Throttle Smoothness
  - Corner Exit Quality
  - Consistency
  - Line Adherence

### Perfect Lap Builder

- Theoretical from best sectors (S1 + S2 + S3)
- Granular theoretical from best segment bins
- Gain vs PB for both estimates

### Post-session output

- JSON report + Markdown report saved in session folder
- Spoken debrief at session end (engineer-style summary)

## Repository Layout

- `marco.py`
  - Entrypoint + menu + phone-triggered start handling
- `marco_core.py`
  - Telemetry loop, coaching logic, analytics pipeline, report generation
- `marco_web.py`
  - Flask + Socket.IO server + state/report API
- `frontend/index.html`
  - Phone UI structure
- `frontend/styles.css`
  - Phone UI styling
- `frontend/app.js`
  - Phone UI rendering + socket/polling + heatmap compare logic
- `DEV_NOTES.md`
  - Engineering notes (state fields, bins, segmentation, thresholds)
- `session_data/`
  - Per-session logs and reports

## Install

Python 3.10+ recommended.

Core:

```bash
pip install pandas pyttsx3
```

Phone UI/API:

```bash
pip install flask flask-socketio qrcode[pil] simple-websocket
```

Optional plotting:

```bash
pip install matplotlib numpy
```

One-shot install:

```bash
pip install pandas pyttsx3 flask flask-socketio qrcode[pil] simple-websocket matplotlib numpy
```

## F1 25 Telemetry Settings

Set in game:

- UDP Telemetry: `On`
- UDP Broadcast Mode: `On`
- UDP IP Address: `127.0.0.1` (same machine) or your PC LAN IP
- UDP Port: `20777`
- UDP Send Rate: `60Hz` (or highest stable)
- UDP Format: `2025`
- Telemetry: `Public`

## Run

```bash
python marco.py
```

Terminal menu:

- `1` Live Coaching Only
- `2` Live Coaching + Telemetry Logging
- `3` Analyze Past Session
- `4` View Track Map from Session
- `5` Exit

## Phone Controls

When Marco starts, it prints a QR code and URL.

Phone buttons:

- `Live Coaching`
- `Coaching + Log` (use this to generate report files)
- `Stop Session`

For full feature testing, use `Coaching + Log`.

## Detailed Test Flow

1. Start `Coaching + Log`.
2. Drive one outlap and at least 3 valid timed laps.
3. Keep compare enabled and switch source:
   - `Current Lap`
   - `Last Lap`
4. Verify UI updates each lap:
   - Top Time Losses
   - Consistency
   - Driver Profile tags
   - Skill scores
   - Corner mastery
   - Optimal lap
5. Stop session and verify:
   - Spoken post-session summary
   - Report files in `session_data/<session_folder>/`

## Phone UI Panels

- Live track map + car dot
- Delta display
- Sector bars
- Fastest lap + lap list
- Compare controls and heatmap overlay
- Top Time Losses
- Consistency card
- Driver Profile tags
- Skill bars
- Corner Mastery list
- Optimal Lap row

## API Endpoints

Base: `http://<pc-ip>:5000`

- `GET /state`
  - Full live state (telemetry + analytics)
- `GET /sessions`
  - Recent sessions + report metadata
- `GET /session/<session_folder>/report`
  - Saved report payload for one session
- `POST /start/1`
  - Start mode 1
- `POST /start/2`
  - Start mode 2
- `POST /stop`
  - Stop active run

Examples:

- `http://192.168.1.42:5000/state`
- `http://192.168.1.42:5000/sessions`
- `http://192.168.1.42:5000/session/session_012_20260219_153000/report`

## `/state` Analytics Fields

In addition to live telemetry fields (`speed`, `gear`, `lap`, `delta`, etc.), `/state` includes:

- `bin_meta`
  - `count`
  - `track_length`
- `reference_bins`
- `current_lap_bins`
- `segment_deltas`
- `last_lap_segment_deltas`
- `heatmap_points`
- `corner_metrics`
- `time_loss_summary`
- `corner_mastery`
- `consistency`
- `driver_profile`
- `skill_scores`
- `optimal_lap`
- `session_report_summary`

## How Key Metrics Are Computed

### Reference lap

- Fastest valid lap in session becomes reference (PB)
- Reference updates when a faster valid lap appears

### Bin comparison

- Lap distance is segmented into fixed bins (`HEATMAP_BIN_COUNT`)
- Cumulative time is interpolated at each bin
- Delta per bin = `current - reference`

### Corner metrics

For each detected corner segment:

- Entry/apex/exit speeds from sampled telemetry
- Brake point = first brake > threshold near corner
- Throttle point = first throttle re-application after apex
- Corner time from interpolated segment entry/exit times
- Delta vs reference from segment time difference

### Consistency

- Lap sigma from recent valid laps
- Sector sigmas from recent S1/S2/S3 histories
- Per-corner sigma from recent corner deltas
- Braking point sigma from recent corner brake distances

### Driver profile (heuristic)

Derived from rolling lap behavior:

- Peak brake and brake slope
- Throttle variability / jerk
- Turn-in rate proxy (steer rate)
- Brake point bias vs reference

### Skill scores

Score outputs are deterministic and metric-based, normalized to 0-100.

## Session Files

Mode 2 output (`session_data/session_###_YYYYMMDD_HHMMSS/`):

- `telemetry.csv`
- `reference_lap.csv` (when PB exists)
- `performance_report.json`
- `performance_report.md`

## Interpreting Report Quality

- 1 valid lap:
  - Baseline only
  - Low-confidence trend/consistency
- 3-5 valid laps:
  - Useful coaching direction
- 8-10 valid laps:
  - Stronger stability and mastery confidence

If your report shows little data, run a longer clean stint.

## Tuning Knobs

Main constants are in `marco_core.py`:

- `HEATMAP_BIN_COUNT`
- `CONSISTENCY_WINDOW_LAPS`
- `CORNER_HISTORY_WINDOW`
- `MAX_CORNER_CALLOUTS_PER_LAP`
- `REPORT_INTERVAL_LAPS`

Corner coaching thresholds:

- `BRAKE_POINT_DIFF_M`
- `ENTRY_SPEED_DIFF_KPH`
- `APEX_SPEED_DIFF_KPH`
- `EXIT_SPEED_DIFF_KPH`
- `THROTTLE_POINT_DIFF_M`

See `DEV_NOTES.md` for implementation details.

## Troubleshooting

### No audio

- Confirm `pyttsx3` is installed
- Check system output device and volume

### No phone dashboard

- Install Flask/Socket.IO dependencies
- Verify phone and PC are on same network
- Open URL manually if QR fails

### UI looks stale after code changes

- Hard refresh mobile browser
- Restart `marco.py`

### Telemetry not arriving

- Re-check in-game UDP settings
- Allow Python/port `20777` through firewall

### Brake warnings too chatty

- Current build already adds anti-repeat phrase logic and reduced warning frequency
- If needed, tune cooldown/threshold constants in `marco_core.py`

## Legacy Scripts

These are kept for experiments/older workflows and are not the recommended runtime path:

- `telemetry_logger.py`
- `realtime_coach.py`
- `analyze_laps.py`
- `visualize_track.py`
- `f1_coach_v2.py`
- `f1_coach_v3.py`
- `marco_v1.py`
