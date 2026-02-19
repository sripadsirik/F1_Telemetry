# F1 Telemetry Coach (Marco v4) - Time Trial Edition

Marco is a **Time-Trial-only** live lap coach for F1 25.

It ingests telemetry, builds a fastest-lap reference, gives corner-specific feedback, shows live comparison visuals on phone, and generates post-session performance reports.

## Core Features

- Live coaching callouts (braking, gear, throttle, speed, corner-specific)
- Sector performance callouts (purple/green/yellow)
- Reference lap from fastest valid lap (PB)
- **Lap Perfection Coach** (turn-specific coaching, capped to avoid spam)
- **Time Loss Finder** (top 3 corners + reason labels)
- **Corner Mastery** (per-turn score + trend)
- **Lap Comparison Heatmap** (compare current or last lap vs PB)
- **Consistency Tracker** (lap/sector/corner/braking variability)
- **Driver Profile Tags** (heuristic style profiling)
- **Skill Scores** (Braking, Throttle, Exit, Consistency, Line)
- **Perfect Lap Builder** (best sectors and best bins estimate)
- **Post-Session Report** (`json` + `md`) and spoken engineer debrief

## Project Layout

- `marco.py`: main entrypoint and terminal menu
- `marco_core.py`: telemetry loop, coach logic, analytics, reporting
- `marco_web.py`: Flask + Socket.IO server and API endpoints
- `frontend/`: phone UI (`index.html`, `styles.css`, `app.js`)
- `session_data/`: generated run folders and outputs
- `DEV_NOTES.md`: implementation details and tunable thresholds

## Requirements

Python 3.10+ recommended.

Core:

```bash
pip install pandas pyttsx3
```

Phone dashboard:

```bash
pip install flask flask-socketio qrcode[pil] simple-websocket
```

Optional plotting:

```bash
pip install matplotlib numpy
```

All at once:

```bash
pip install pandas pyttsx3 flask flask-socketio qrcode[pil] simple-websocket matplotlib numpy
```

## F1 25 Telemetry Settings (Required)

- UDP Telemetry: `On`
- UDP Broadcast Mode: `On`
- UDP IP Address: `127.0.0.1` (local) or your PC LAN IP
- UDP Port: `20777`
- UDP Send Rate: `60Hz` (or highest stable)
- UDP Format: `2025`
- Telemetry: `Public`

## Quick Start

Run:

```bash
python marco.py
```

Terminal menu:

- `1` Live Coaching Only
- `2` Live Coaching + Telemetry Logging
- `3` Analyze Past Session
- `4` View Track Map from Session
- `5` Exit

Phone flow:

- Launching `marco.py` prints QR + URL
- Open URL on phone
- Use:
  - `Live Coaching` (mode 1)
  - `Coaching + Log` (mode 2, required for report files)
  - `Stop Session`

## Recommended Test Flow (Phone)

1. Tap `Coaching + Log`.
2. Drive 1 outlap + at least 3 valid laps.
3. Keep `Compare vs PB` enabled.
4. Toggle compare source (`Current Lap` / `Last Lap`) to test heatmap modes.
5. Check UI cards update per lap:
   - Top Time Losses
   - Consistency
   - Driver Profile
   - Skill Scores
   - Corner Mastery
   - Optimal Lap
6. Tap `Stop Session` and listen for the post-session spoken summary.

## Phone UI Sections

- Live track + car marker
- Delta display
- Sector status bars
- Lap list + fastest lap
- Compare controls + heatmap overlay
- Top Time Losses
- Consistency card
- Driver profile tags
- Skill bars
- Corner mastery list
- Optimal lap estimate

## API Endpoints

Base URL: `http://<pc-ip>:5000`

- `GET /state`
  - Current live state + TT analytics payload
- `GET /sessions`
  - Recent sessions + report availability/summary
- `GET /session/<session_folder>/report`
  - Performance report JSON for a session
- `POST /start/1`
  - Start live coaching
- `POST /start/2`
  - Start coaching + logging
- `POST /stop`
  - Stop active session

Example:

- `http://192.168.1.42:5000/state`
- `http://192.168.1.42:5000/sessions`
- `http://192.168.1.42:5000/session/session_012_20260219_153000/report`

## Session Output Files

When logging is enabled (mode 2):

- `session_data/session_###_YYYYMMDD_HHMMSS/telemetry.csv`
- `session_data/session_###_YYYYMMDD_HHMMSS/reference_lap.csv` (when PB exists)
- `session_data/session_###_YYYYMMDD_HHMMSS/performance_report.json`
- `session_data/session_###_YYYYMMDD_HHMMSS/performance_report.md`

## Reading Report Quality

- 1 valid lap: baseline only, low-confidence trend/consistency signals
- 3-5 valid laps: useful coaching trends
- 8-10 valid laps: stronger consistency/mastery confidence

## Troubleshooting

### No audio

- Install `pyttsx3`
- Check output device/mute
- Run in normal desktop session

### No phone dashboard

- Install Flask/Socket.IO dependencies
- Confirm phone + PC are on same network
- Open printed URL manually if QR fails

### UI stale after updates

- Hard refresh phone browser
- Restart `marco.py`

### Telemetry not arriving

- Re-check in-game UDP settings
- Allow Python/port `20777` through firewall

## Legacy Scripts

Older scripts are still present but not the main runtime path:

- `telemetry_logger.py`
- `realtime_coach.py`
- `analyze_laps.py`
- `visualize_track.py`
- `f1_coach_v2.py`, `f1_coach_v3.py`, `marco_v1.py`

