# F1 Telemetry Coach (Marco v4)

Real-time race engineer for F1 25 with live audio coaching, session logging, lap analysis, and a phone dashboard.

This repository currently has two layers:
- Main app (`marco.py`) with modular backend (`marco_core.py`, `marco_web.py`) and phone frontend (`frontend/`)
- Legacy/utility scripts (`telemetry_logger.py`, `realtime_coach.py`, `analyze_laps.py`, etc.)

The recommended runtime is the modular Marco app.

## What Marco Does

During a live session, Marco can:
- Ingest F1 25 UDP telemetry (`2025` packet format)
- Speak coaching callouts (braking, gear, speed, throttle, corner feedback)
- Track invalid laps, warnings/penalties, crash events, and damage
- Announce sector performance (purple/green/yellow) and full lap times
- Build/update a reference lap from your fastest valid lap
- Log telemetry per session to `session_data/session_.../telemetry.csv`
- Show a phone dashboard with:
  - live map + car marker
  - speed/gear/lap/delta
  - sector status rectangles
  - fastest lap and lap history
  - remote start/stop controls

## Current Project Structure

- `marco.py`
  - Main entrypoint and terminal menu
  - Starts web server (if dependencies are installed)
  - Handles phone-triggered mode starts while terminal is idle

- `marco_core.py`
  - Core coach logic and telemetry pipeline
  - Track/corner analysis
  - Session creation/logging/analysis/plotting functions
  - Shared runtime state used by phone dashboard

- `marco_web.py`
  - Flask + Socket.IO server
  - QR/url display in terminal
  - `/state`, `/start/<mode>`, `/stop`, `/sessions`
  - live telemetry/updates to phone clients

- `frontend/`
  - `index.html`: phone UI layout
  - `styles.css`: phone UI styles
  - `app.js`: phone UI logic (socket + polling fallback, rendering)

- `session_data/`
  - Created automatically
  - Contains run folders (`session_###_timestamp`) with telemetry and references

- `logs/`
  - Older scripts output and examples

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

Plotting (analysis charts):
```bash
pip install matplotlib numpy
```

Or install everything at once:
```bash
pip install pandas pyttsx3 flask flask-socketio qrcode[pil] simple-websocket matplotlib numpy
```

## F1 25 Telemetry Settings (Required)

In-game telemetry settings should be:
- UDP Telemetry: `On`
- UDP Broadcast Mode: `On`
- UDP IP Address: `127.0.0.1` (same machine) or your PC LAN IP if needed
- UDP Port: `20777`
- UDP Send Rate: `60Hz` (or highest stable)
- UDP Format: `2025`
- Telemetry: `Public` (not Restricted)

If telemetry does not arrive, verify firewall rules allow Python/port `20777`.

## Quick Start

Run the app:
```bash
python marco.py
```

From terminal menu:
- `1` Live Coaching Only
- `2` Live Coaching + Telemetry Logging
- `3` Analyze Past Session
- `4` View Track Map from Session
- `5` Exit

Phone control:
- Launching `marco.py` prints a QR and URL
- Open the phone page on the same network
- Start/stop sessions from phone or terminal

## Runtime Behavior

### Session modes
- Mode 1: coaching only
- Mode 2: coaching + CSV logging per session folder

### Reference lap
- Fastest valid lap in-session becomes current reference
- Reference updates live as you set better laps
- Sector comparisons use best/reference timings

### Phone dashboard state
- Live values are streamed with Socket.IO
- Fallback polling is active for resilience
- Ending a session clears dashboard state so a new track starts clean

## Session Data and Analysis

When logging is enabled (mode 2), each run creates:
- `session_data/session_###_YYYYMMDD_HHMMSS/telemetry.csv`
- `session_data/session_###_YYYYMMDD_HHMMSS/reference_lap.csv` (when available)

You can analyze from menu options 3 and 4:
- Summary of laps (complete/invalid)
- Fastest valid lap selection
- Optional plots (track map, speed, throttle/brake, gear)

## Troubleshooting

### No coaching audio
- Install `pyttsx3`
- Check OS output device/mute
- Keep app running in a normal desktop session

### No phone dashboard
- Install Flask/Socket.IO dependencies
- Confirm phone and PC are on same network
- Open printed URL manually if QR scan fails

### Phone values update but map/dot missing
- Make sure motion packets are being sent by game
- Hard-refresh phone page after frontend changes
- Verify `frontend/app.js` loaded (browser cache can hold old assets)

### Session starts on terminal but not immediately on phone
- Use current codebase (`marco.py` + `marco_web.py` + `frontend/`)
- Ensure page is refreshed and websocket/poll fallback is active

### Track changed but old map remains
- Use Stop Session from phone or terminal
- App now clears live phone state at session end

## Legacy Scripts (Still Present)

These scripts are older/alternate workflows and can still be used independently:
- `telemetry_logger.py`
- `realtime_coach.py`
- `analyze_laps.py`
- `visualize_track.py`
- `f1_coach_v2.py`, `f1_coach_v3.py`, `marco_v1.py`

They are not the primary path for the current modular phone-enabled app.

## Development Notes

- Main shared state lives in `marco_core.py` (`shared_state`)
- Web server reads/writes through that shared state
- Frontend is static files served from `frontend/`
- If you change frontend files, hard-refresh mobile browser to bust cache

## Suggested Next Improvements

- Add `requirements.txt` or `pyproject.toml` for one-command setup
- Add unit tests around lap/sector transition logic
- Add explicit versioned API schema for phone state payload
- Add optional multi-client session viewer and role controls
