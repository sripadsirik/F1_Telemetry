# Marco — F1 25 Race Engineer

Marco is a **Time-Trial-only** live lap engineer for F1 25.

It listens to UDP telemetry from the game, builds a fastest-lap reference, compares every lap against it in real time, gives concise voice coaching, and pushes a live dashboard to any browser on your network — including your phone.

---

## Download & Run (no setup required)

> **Grab the latest release from the [Releases](../../releases/latest) page.**

1. Download `Marco.zip` from the release assets
2. Extract the `Marco/` folder anywhere on your PC
3. Double-click `Marco.exe`
4. A console opens, prints a QR code — scan it with your phone

That's it. No Python, no Node, no install needed.

---

## What You Get

### Live voice coaching
- Brake zone warnings and "brake now" calls
- Gear and throttle prompts
- Sector time callouts — purple / green / yellow
- Corner-by-corner feedback (capped at 4 per lap, 1 per corner)

### Telemetry dashboard (phone or browser)
- Live track map with car dot
- Delta display and sector bars
- Lap time list with PB / invalid / OK tags
- Heatmap overlay — green where you're faster, red where you're losing time
- Compare: current lap vs PB, or last lap vs PB

### Analytics cards (update automatically each lap)
| Card | What it shows |
|---|---|
| Top Time Losses | Corners costing you the most time |
| Consistency | Lap σ, sector σ, most / least consistent corner |
| Driver Profile | Heuristic tags — Aggressive Braker, Smooth Throttle, etc. |
| Skill Scores | 0–100 bars for Braking, Throttle, Exit, Consistency, Line |
| Corner Mastery | Per-corner score + trend (↑ ↓ →) |
| Optimal Lap | Theoretical best from sectors and bins |

### Post-session report
- JSON + Markdown report saved to `session_data/`
- Spoken engineer-style debrief at session end

---

## F1 25 Telemetry Settings

In-game → Settings → Telemetry:

| Setting | Value |
|---|---|
| UDP Telemetry | On |
| UDP Broadcast Mode | On |
| UDP IP Address | `127.0.0.1` (same PC) or your PC's LAN IP |
| UDP Port | `20777` |
| UDP Send Rate | 60 Hz (or highest stable) |
| UDP Format | 2025 |
| Telemetry | Public |

---

## Screens

### Menu screen (`/`)
- Start Coaching (voice only)
- Start Coaching + Logging (saves CSV + report)
- Telemetry Dashboard shortcut
- Session summary — laps completed, best lap, optimal lap

### Telemetry screen (`/telemetry`)
- Full live dashboard
- Back button to menu
- Start / Stop controls

---

## Running from source

### Requirements
- Python 3.10+
- Node.js 18+ (for frontend build only)

### Install
```bash
# Python deps
python -m venv venv
venv\Scripts\activate       # Windows
pip install -r requirements.txt

# Frontend (one-time build)
cd frontend
npm install
npm run build
cd ..
```

### Run
```bash
python marco.py
```

Open the printed URL (or scan the QR code) on any device on the same Wi-Fi.

### Local dev (hot-reload UI)
```
Terminal 1:  python marco.py          # backend on :5000
Terminal 2:  cd frontend && npm run dev   # Vite on :5173
```
Open `http://localhost:5173` — UI reloads instantly on file saves.

---

## Building the .exe yourself

```powershell
.\build_exe.ps1
```

This runs `npm run build` then PyInstaller. Output: `dist\Marco\Marco.exe`.

> Distribute the entire `dist\Marco\` folder — the `.exe` needs the `_internal\` folder next to it.

---

## Voice settings

Controlled via environment variables (set before launching):

| Variable | Default | Description |
|---|---|---|
| `MARCO_TTS_RATE` | `170` | Words per minute — lower = calmer |
| `MARCO_TTS_VOLUME` | `0.9` | Volume 0.0–1.0 |
| `MARCO_TTS_VOICE` | `female` | Substring matched against voice name (e.g. `zira`, `hazel`) |
| `MARCO_USE_NEURAL` | _(off)_ | Set to `1` to use edge-tts neural voice |
| `MARCO_NEURAL_VOICE` | `en-GB-SoniaNeural` | edge-tts voice name |

Neural voice (much more natural) requires `pip install edge-tts` and `MARCO_USE_NEURAL=1`.

---

## Repository layout

```
marco.py            — entry point and terminal menu
marco_core.py       — telemetry loop, coaching, analytics, TTS
marco_web.py        — Flask + Socket.IO server and REST API
marco.spec          — PyInstaller build spec
build_exe.ps1       — full build pipeline script
requirements.txt    — Python dependencies
frontend/
  src/              — React + TypeScript source (Vite)
  dist/             — built output served by Flask (gitignored, regenerated)
session_data/       — per-session CSV logs and reports (gitignored)
```

---

## API

Base URL: `http://<pc-ip>:5000`

| Method | Endpoint | Description |
|---|---|---|
| GET | `/state` | Full live state — telemetry + all analytics |
| POST | `/start/1` | Start coaching (voice only) |
| POST | `/start/2` | Start coaching + logging |
| POST | `/stop` | Stop active session |
| GET | `/sessions` | List recent sessions |
| GET | `/session/<id>/report` | Load saved JSON report |

Socket.IO events pushed to clients:

| Event | Rate | Payload |
|---|---|---|
| `telemetry` | 10 ms | speed, gear, position, delta, sector |
| `session_state` | 1 s | full state including all analytics |

---

## Tuning constants (`marco_core.py`)

```python
HEATMAP_BIN_COUNT          = 320   # lap distance bins
CONSISTENCY_WINDOW_LAPS    = 10    # rolling window for sigma
CORNER_HISTORY_WINDOW      = 12    # corner data history
MAX_CORNER_CALLOUTS_PER_LAP = 4   # anti-spam cap
REPORT_INTERVAL_LAPS       = 3    # laps between auto-reports

BRAKE_POINT_DIFF_M         = 10.0  # coaching thresholds
ENTRY_SPEED_DIFF_KPH       = 8.0
APEX_SPEED_DIFF_KPH        = 6.0
EXIT_SPEED_DIFF_KPH        = 8.0
THROTTLE_POINT_DIFF_M      = 15.0
```

---

## Troubleshooting

**No voice** — check `pyttsx3` is installed and your system audio output is set correctly.

**Phone can't connect** — make sure phone and PC are on the same Wi-Fi. Try typing the URL manually. Allow port `5000` through Windows Firewall.

**No telemetry data** — re-check in-game UDP settings. Allow port `20777` through firewall.

**Dashboard went blank** — this was a known bug fixed in v4.1 (null-safety + error boundary). Update to the latest release.

**UI feels stale** — the dashboard auto-refreshes every 1 s via Socket.IO. If it seems frozen, check the "Live / Polling" indicator in the top-right corner of the dashboard.

---

## Session output (mode 2)

Saved to `session_data/session_###_YYYYMMDD_HHMMSS/`:

- `telemetry.csv` — raw frame-by-frame data
- `reference_lap.csv` — the current PB lap
- `performance_report.json` — structured analytics
- `performance_report.md` — human-readable summary

Report quality improves with more clean laps — 8–10 laps gives the strongest consistency and mastery data.
