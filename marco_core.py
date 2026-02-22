"""
================================================================================
  MARCO - F1 25 RACE ENGINEER v4.0
================================================================================

  Features:
  - Live predictive coaching with audio callouts
  - Sector time callouts (purple/green/yellow)
  - Corner-by-corner feedback
  - Delta callouts per sector (not spammed)
  - Crash detection, invalid lap handling, damage monitoring
  - Telemetry logging to CSV (organized by session)
  - Post-session analysis and visualization
  - Phone web interface with live track map and lap times

================================================================================
"""

import socket
import struct
import pandas as pd
import csv
import os
import sys
import time
import threading
import queue
import random
import re
import json
import logging
import statistics
import bisect
from datetime import datetime

# Optional imports
try:
    import pyttsx3
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False

# Optional: edge-tts neural voice (pip install edge-tts)
try:
    import edge_tts as _edge_tts_module
    import asyncio as _asyncio
    import tempfile as _tempfile
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

try:
    import matplotlib.pyplot as plt
    import numpy as np
    PLOTTING_AVAILABLE = True
except ImportError:
    PLOTTING_AVAILABLE = False

# =============================================================================
# CONFIGURATION
# =============================================================================
UDP_IP = "0.0.0.0"
UDP_PORT = 20777
SESSION_DATA_DIR = "session_data"
COACH_NAME = "Marco"

# Time-trial analytics settings
HEATMAP_BIN_COUNT = 320
CONSISTENCY_WINDOW_LAPS = 10
CORNER_HISTORY_WINDOW = 12
MAX_CORNER_CALLOUTS_PER_LAP = 4
REPORT_INTERVAL_LAPS = 3

# Corner coaching thresholds
BRAKE_POINT_DIFF_M = 10.0
ENTRY_SPEED_DIFF_KPH = 8.0
APEX_SPEED_DIFF_KPH = 6.0
EXIT_SPEED_DIFF_KPH = 8.0
THROTTLE_POINT_DIFF_M = 15.0

# ---------------------------------------------------------------------------
# TTS voice configuration
#   Override via environment variables:
#     MARCO_TTS_RATE   – words-per-minute  (default 170; lower = calmer)
#     MARCO_TTS_VOLUME – 0.0–1.0           (default 0.9)
#     MARCO_TTS_VOICE  – substring to match against voice name/id
#                        e.g. "zira", "female", "hazel", "david"
#     MARCO_USE_NEURAL – set to "1" to use edge-tts if installed
#     MARCO_NEURAL_VOICE – edge-tts voice name (default en-GB-SoniaNeural)
# ---------------------------------------------------------------------------
MARCO_TTS_RATE   = int(os.environ.get('MARCO_TTS_RATE', '170'))
MARCO_TTS_VOLUME = float(os.environ.get('MARCO_TTS_VOLUME', '0.9'))
MARCO_TTS_VOICE  = os.environ.get('MARCO_TTS_VOICE', 'female').lower()
MARCO_USE_NEURAL = os.environ.get('MARCO_USE_NEURAL', '').lower() in ('1', 'true', 'yes')
MARCO_NEURAL_VOICE = os.environ.get('MARCO_NEURAL_VOICE', 'en-GB-SoniaNeural')

# Cache for the selected pyttsx3 voice id (selected once on first use)
_tts_voice_id: 'str | None' = None
_tts_voice_selected: bool = False


def _select_tts_voice(engine) -> 'str | None':
    """Pick the most soothing available voice and return its id."""
    voices = engine.getProperty('voices')
    if not voices:
        return None

    print("  [TTS] Available voices:")
    for v in voices:
        print(f"    • {v.name}  ({v.id})")

    target = MARCO_TTS_VOICE  # already lower-cased

    # 1) Try user-specified substring first
    for v in voices:
        if target in v.name.lower() or target in v.id.lower():
            print(f"  [TTS] Selected voice: {v.name}")
            return v.id

    # 2) Fallback: well-known soothing voices (Windows/macOS/Linux)
    preferred_names = ['zira', 'hazel', 'susan', 'karen', 'victoria',
                       'female', 'woman', 'samantha', 'aria', 'jenny']
    for pref in preferred_names:
        for v in voices:
            if pref in v.name.lower() or pref in v.id.lower():
                print(f"  [TTS] Selected voice (fallback): {v.name}")
                return v.id

    # 3) Any non-first voice
    if len(voices) > 1:
        print(f"  [TTS] Selected voice (second available): {voices[1].name}")
        return voices[1].id

    print(f"  [TTS] Using default voice: {voices[0].name}")
    return voices[0].id


def _configure_tts_engine(engine) -> None:
    """Apply rate/volume/voice settings to a pyttsx3 engine instance."""
    global _tts_voice_id, _tts_voice_selected
    engine.setProperty('rate', MARCO_TTS_RATE)
    engine.setProperty('volume', MARCO_TTS_VOLUME)
    if not _tts_voice_selected:
        _tts_voice_id = _select_tts_voice(engine)
        _tts_voice_selected = True
    if _tts_voice_id:
        try:
            engine.setProperty('voice', _tts_voice_id)
        except Exception:
            pass  # voice id may be invalid on some platforms


def _speak_neural(message: str) -> bool:
    """Speak using edge-tts neural voice. Returns True on success."""
    if not (EDGE_TTS_AVAILABLE and MARCO_USE_NEURAL):
        return False
    try:
        async def _gen(path: str) -> None:
            c = _edge_tts_module.Communicate(message, MARCO_NEURAL_VOICE)
            await c.save(path)

        with _tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            tmp = f.name

        loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_gen(tmp))
        finally:
            loop.close()

        # Play on Windows via PowerShell MediaPlayer (no extra dependency)
        import subprocess
        cmd = (
            f"Add-Type -AssemblyName presentationCore; "
            f"$p=New-Object System.Windows.Media.MediaPlayer; "
            f"$p.Open([uri]::new('{tmp}')); "
            f"$p.Play(); Start-Sleep -s 10; $p.Close()"
        )
        subprocess.run(
            ['powershell', '-NoProfile', '-Command', cmd],
            capture_output=True, timeout=15
        )
        return True
    except Exception as exc:
        print(f"  [edge-tts error: {exc}]")
        return False
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def _default_analytics_state():
    return {
        'reference_bins': [],
        'current_lap_bins': [],
        'segment_deltas': [],
        'last_lap_segment_deltas': [],
        'heatmap_points': [],
        'bin_meta': {
            'count': HEATMAP_BIN_COUNT,
            'track_length': 0.0,
        },
        'corner_metrics': [],
        'corner_mastery': [],
        'consistency': {
            'lap_sigma': None,
            'sector_sigma': {'s1': None, 's2': None, 's3': None},
            'most_inconsistent_corner': None,
            'most_consistent_corner': None,
            'braking_point_sigma': None,
        },
        'driver_profile': {
            'tags': [],
            'stats': {},
        },
        'skill_scores': {},
        'optimal_lap': {
            'sectors_best': None,
            'bins_best': None,
            'gain_vs_pb_sectors': None,
            'gain_vs_pb_bins': None,
        },
        'time_loss_summary': [],
        'session_report_summary': None,
    }

# Packet formats - F1 25
HEADER_FMT = '<HBBBBBQfIIBB'
HEADER_SIZE = struct.calcsize(HEADER_FMT)

CAR_TELEM_FMT = '<HfffBbHBBHHHHHBBBBBBBBHffffBBBB'
CAR_TELEM_SIZE = struct.calcsize(CAR_TELEM_FMT)

LAP_DATA_FMT = '<IIHBHBHBHBfffBBBBBBBBBBBBBBHHBfB'
LAP_DATA_SIZE = struct.calcsize(LAP_DATA_FMT)

MOTION_FMT = '<ffffff'
MOTION_SIZE = struct.calcsize(MOTION_FMT)


# =============================================================================
# SHARED STATE (for web interface)
# =============================================================================
shared_state = {
    'coach': None,
    'start_queue': queue.Queue(),
    'stop_queue': queue.Queue(),
    'lap_times': [],
    'position': {'x': 0, 'z': 0},
    'track_outline': [],
    'session_active': False,
    'current_mode': None,
    'current_speed': 0,
    'current_gear': 0,
    'current_lap_num': 0,
    'current_lap_time': 0,
    'current_delta': 0,
    'current_sector': 0,
    'socketio': None,
    'speech_log': [],
    'fastest_lap': None,
    'sector_colors': {1: None, 2: None, 3: None},
    **_default_analytics_state(),
}


def _reset_analytics_shared_state():
    """Reset derived analytics fields used by the web UI."""
    shared_state.update(_default_analytics_state())


# =============================================================================
# DIALOGUE BANK
# =============================================================================
DIALOGUES = {
    'intro': [
        f"Hey, it's {COACH_NAME}. I'm your race engineer today. Get out there, put in a clean lap, and I'll start coaching you from there.",
    ],
    'formation_lap': [
        "Connected. Telemetry online. Formation lap, take it easy.",
        "Got you on screen. Outlap, warming up the tires.",
        "Telemetry online. Formation lap, no need to push yet.",
    ],
    'lap_start_no_ref': [
        "Lap {lap}. Push hard, this one sets the reference.",
        "Lap {lap}. Give me a clean one, I need baseline data.",
        "Lap {lap}. Show me what you've got.",
    ],
    'lap_start_with_ref': [
        "Lap {lap}. Let's go.",
        "Lap {lap}. Target is {target}.",
        "Lap {lap}. Stay focused.",
    ],
    'baseline_set': [
        "Nice one. {time}. That's our baseline. Now let's beat it.",
        "Good lap. {time}. I've got the data, now let's improve.",
        "{time}. Solid baseline. I'll guide you from here.",
    ],
    'purple_lap': [
        "Purple! {time}. That's {delta} faster. New reference.",
        "Fastest lap! {time}. You found {delta}.",
        "Beautiful! {time}, {delta} quicker.",
    ],
    'lap_close': [
        "{time}. Just {delta} off. You've got the pace.",
        "{time}. Within {delta}. Keep at it.",
        "{time}. Only {delta} down.",
    ],
    'lap_ok': [
        "{time}. Plus {delta}. Time on the table.",
        "{time}. Lost {delta} there.",
        "{time}. {delta} off the pace.",
    ],
    'lap_slow': [
        "{time}. Lost {delta} seconds. Tighten it up.",
        "{time}. {delta} down. Reset and go again.",
        "{time}. {delta} off. Focus on the next lap.",
    ],

    # Invalid lap
    'lap_invalidated': ["Lap invalid.", "That lap won't count.", "Lap deleted."],
    'lap_invalid_corner_cut': ["Track limits. Lap invalid.", "Corner cut. Lap's gone.", "Exceeded track limits."],
    'lap_invalid_wall': ["Wall contact. Lap invalid.", "Touched the barrier. Lap's gone."],
    'lap_invalid_running_wide': ["Ran wide. Lap invalid.", "Too wide on exit. Lap deleted."],
    'lap_invalid_reset': ["Reset detected. Lap invalid."],
    'lap_invalid_flashback': ["Flashback used. Lap invalid."],

    # Crashes
    'crash_heavy': ["Big impact. Check your damage.", "That was a heavy one.", "Into the barriers. Shake it off."],
    'crash_light': ["Small contact.", "Light touch.", "Bit of a tap there."],
    'collision_car': ["Contact with another car.", "Car collision."],

    # Damage
    'damage_front_wing_light': ["Minor front wing damage.", "Front wing took a hit."],
    'damage_front_wing_heavy': ["Heavy front wing damage. Be careful in corners.", "Significant wing damage."],
    'damage_rear_wing': ["Rear wing damage."],
    'damage_floor': ["Floor damage. You'll feel it in the corners."],

    # Penalties
    'penalty_warning': ["That's a warning. Keep it clean.", "Warning from race control."],
    'penalty_corner_cutting': ["Track limits warning.", "Corner cutting warning."],
    'penalty_time': ["{seconds} second penalty."],

    # Braking
    'brake_warning': [
        "Big stop coming",
        "Heavy braking ahead",
        "Braking zone ahead",
        "Prepare for the stop",
        "Hard braking next",
    ],
    'brake_now': ["Brake", "Brake now"],
    'brake_with_gear': ["Brake, {gear}", "Brake, down to {gear}"],

    # Coaching
    'downshift': ["Down to {gear}", "{gear}"],
    'get_on_power': ["Power", "Throttle"],
    'carry_more_speed': ["More speed here", "Carry more speed"],
    'good_speed': ["Good speed", "Nice"],

    # Delta (per sector now)
    'delta_plus': ["Plus {delta}"],
    'delta_minus': ["Minus {delta}"],

    # Sector times
    'sector_purple': [
        "Sector {sector} purple, {time}",
        "Purple sector {sector}, {time}",
    ],
    'sector_green': [
        "Sector {sector} green, {time}",
        "Good sector {sector}, {time}",
    ],
    'sector_yellow': [
        "Sector {sector}, plus {delta}",
    ],

    # Corner feedback
    'corner_brake_later': ["Turn {turn}, brake later"],
    'corner_good_brake': ["Turn {turn}, good late brake"],
    'corner_carry_speed': ["Turn {turn}, carry more speed"],
    'corner_good_speed': ["Turn {turn}, good speed"],
    'corner_earlier_throttle': ["Turn {turn}, earlier throttle"],
    'corner_good_exit': ["Turn {turn}, good drive out"],
    'corner_good': ["Good turn {turn}"],
    'corner_brake_earlier': ["Turn {turn}, brake earlier"],
    'corner_focus_exit': ["Turn {turn}, prioritize exit speed"],
    'corner_overslow_apex': ["Turn {turn}, don't over-slow apex"],
    'corner_entry_speed': ["Turn {turn}, carry entry speed"],
    'lap_time_loss_summary': ["Biggest loss, turn {turn}, plus {delta}"],

    # Session
    'session_end': ["Good session. See you next time.", "Session complete. Nice work."],
}

_LAST_SAY_BY_CATEGORY = {}

def say(category, **kwargs):
    phrases = DIALOGUES.get(category, [category])
    if len(phrases) > 1:
        last_phrase = _LAST_SAY_BY_CATEGORY.get(category)
        options = [p for p in phrases if p != last_phrase]
        phrase = random.choice(options if options else phrases)
    else:
        phrase = phrases[0]
    _LAST_SAY_BY_CATEGORY[category] = phrase
    return phrase.format(**kwargs) if kwargs else phrase


# =============================================================================
# SESSION MANAGER - Handles folder creation and session tracking
# =============================================================================
class SessionManager:
    """Manages session folders and file paths."""

    def __init__(self):
        self.base_dir = SESSION_DATA_DIR
        os.makedirs(self.base_dir, exist_ok=True)

    def get_existing_sessions(self):
        """Get list of existing session folders, sorted by number."""
        if not os.path.exists(self.base_dir):
            return []

        sessions = []
        for folder in os.listdir(self.base_dir):
            folder_path = os.path.join(self.base_dir, folder)
            if os.path.isdir(folder_path) and folder.startswith('session_'):
                match = re.match(r'session_(\d+)', folder)
                if match:
                    num = int(match.group(1))
                    csv_path = os.path.join(folder_path, 'telemetry.csv')
                    if os.path.exists(csv_path):
                        sessions.append({
                            'number': num,
                            'folder': folder,
                            'path': folder_path,
                            'csv_path': csv_path,
                        })

        sessions.sort(key=lambda x: x['number'])
        return sessions

    def create_new_session(self):
        """Create a new session folder and return its path."""
        sessions = self.get_existing_sessions()

        if sessions:
            next_num = sessions[-1]['number'] + 1
        else:
            next_num = 1

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        folder_name = f"session_{next_num:03d}_{timestamp}"
        folder_path = os.path.join(self.base_dir, folder_name)

        os.makedirs(folder_path, exist_ok=True)

        return {
            'number': next_num,
            'folder': folder_name,
            'path': folder_path,
            'csv_path': os.path.join(folder_path, 'telemetry.csv'),
            'reference_path': os.path.join(folder_path, 'reference_lap.csv'),
        }

    def get_session_info(self, session_path):
        """Get info about a session from its CSV file."""
        csv_path = os.path.join(session_path, 'telemetry.csv')
        if not os.path.exists(csv_path):
            return None

        try:
            df = pd.read_csv(csv_path)
            size_kb = os.path.getsize(csv_path) / 1024
            num_points = len(df)
            laps = sorted(df['current_lap_num'].unique()) if 'current_lap_num' in df.columns else []
            racing_laps = [l for l in laps if l >= 1]

            return {
                'points': num_points,
                'size_kb': size_kb,
                'laps': racing_laps,
                'num_laps': len(racing_laps),
            }
        except Exception as e:
            return None


# =============================================================================
# TRACK ANALYZER
# =============================================================================
class TrackAnalyzer:
    """Analyzes reference lap for braking zones and corner data."""

    def __init__(self, reference_df):
        self.reference = reference_df.sort_values('lap_distance').reset_index(drop=True)
        self.braking_zones = []
        self.corners = []
        self.track_length = self.reference['lap_distance'].max()
        self._analyze()

    def _analyze(self):
        df = self.reference.copy()
        df['brake_smooth'] = df['brake'].rolling(window=5, min_periods=1).mean()
        if 'steer' in df.columns:
            df['steer_smooth'] = df['steer'].abs().rolling(window=7, min_periods=1).mean()
        else:
            df['steer_smooth'] = 0.0

        in_braking = False
        zone_start = None

        for idx, row in df.iterrows():
            if row['brake_smooth'] > 0.2 and not in_braking:
                in_braking = True
                zone_start = idx
            elif row['brake_smooth'] < 0.1 and in_braking:
                in_braking = False
                if zone_start is not None:
                    zone_data = df.iloc[zone_start:idx]
                    if len(zone_data) > 3:
                        brake_start_dist = zone_data['lap_distance'].iloc[0]

                        min_speed_idx = zone_data['speed'].idxmin()
                        min_speed_dist = df.loc[min_speed_idx, 'lap_distance']
                        min_speed_val = zone_data['speed'].min()

                        post_corner = df.iloc[min_speed_idx:min(min_speed_idx + 120, len(df))]
                        throttle_on_dist = None
                        for _, r in post_corner.iterrows():
                            if r['throttle'] > 0.5:
                                throttle_on_dist = r['lap_distance']
                                break

                        exit_dist = zone_data['lap_distance'].iloc[-1]
                        exit_buffer_dist = exit_dist + 50

                        self.braking_zones.append({
                            'start_dist': brake_start_dist,
                            'end_dist': exit_dist,
                            'exit_dist': exit_buffer_dist,
                            'entry_speed': zone_data['speed'].iloc[0],
                            'min_speed': min_speed_val,
                            'min_speed_dist': min_speed_dist,
                            'min_gear': int(zone_data['gear'].min()),
                            'brake_start_dist': brake_start_dist,
                            'throttle_on_dist': throttle_on_dist,
                        })

        def finalize_steering_corner(start_idx, end_idx):
            if start_idx is None or end_idx <= start_idx:
                return None
            zone_data = df.iloc[start_idx:end_idx]
            if len(zone_data) < 6:
                return None

            start_dist = zone_data['lap_distance'].iloc[0]
            end_dist = zone_data['lap_distance'].iloc[-1]
            if (end_dist - start_dist) < 20:
                return None

            min_speed_idx = zone_data['speed'].idxmin()
            min_speed_dist = df.loc[min_speed_idx, 'lap_distance']
            min_speed_val = zone_data['speed'].min()

            post_corner = df.iloc[min_speed_idx:min(min_speed_idx + 120, len(df))]
            throttle_on_dist = None
            for _, r in post_corner.iterrows():
                if r['throttle'] > 0.5:
                    throttle_on_dist = r['lap_distance']
                    break

            brake_dist = None
            for _, r in zone_data.iterrows():
                if r['brake'] > 0.2:
                    brake_dist = r['lap_distance']
                    break

            return {
                'start_dist': start_dist,
                'end_dist': end_dist,
                'exit_dist': end_dist + 45,
                'entry_speed': zone_data['speed'].iloc[0],
                'min_speed': min_speed_val,
                'min_speed_dist': min_speed_dist,
                'min_gear': int(zone_data['gear'].min()),
                'brake_start_dist': brake_dist,
                'throttle_on_dist': throttle_on_dist,
            }

        steering_corners = []
        if 'steer' in df.columns:
            in_corner = False
            corner_start = None
            steer_threshold = 0.12

            for idx, row in df.iterrows():
                steering_active = row['steer_smooth'] > steer_threshold
                if steering_active and not in_corner:
                    in_corner = True
                    corner_start = idx
                elif not steering_active and in_corner:
                    in_corner = False
                    corner = finalize_steering_corner(corner_start, idx)
                    if corner:
                        steering_corners.append(corner)
                    corner_start = None

            if in_corner and corner_start is not None:
                corner = finalize_steering_corner(corner_start, len(df))
                if corner:
                    steering_corners.append(corner)

        self.braking_zones.sort(key=lambda z: z['start_dist'])

        extra_corners = []
        for corner in steering_corners:
            overlaps = False
            for zone in self.braking_zones:
                ranges_overlap = (
                    corner['start_dist'] <= (zone['end_dist'] + 45)
                    and corner['end_dist'] >= (zone['start_dist'] - 45)
                )
                same_apex = abs(corner['min_speed_dist'] - zone['min_speed_dist']) < 80
                if ranges_overlap or same_apex:
                    overlaps = True
                    break
            if not overlaps:
                extra_corners.append(corner)

        self.corners = self.braking_zones + extra_corners
        self.corners.sort(key=lambda z: z['start_dist'])

        if len(self.corners) < 3:
            fallback_corners = self._build_fallback_corners(df)
            if len(fallback_corners) > len(self.corners):
                self.corners = fallback_corners

        for idx, zone in enumerate(self.corners, start=1):
            zone['turn_number'] = idx
            zone['start_distance'] = zone['start_dist']
            zone['apex_distance'] = zone['min_speed_dist']
            zone['end_distance'] = zone['exit_dist']

        print(f"\n  Track Analysis:")
        print(f"  - Length: {self.track_length:.0f}m")
        print(f"  - Braking zones: {len(self.braking_zones)}")
        print(f"  - Turns detected: {len(self.corners)}")
        for z in self.corners:
            print(f"    T{z['turn_number']}: {z['start_dist']:.0f}m | {z['entry_speed']:.0f}->{z['min_speed']:.0f} km/h | G{z['min_gear']}")

    def get_next_braking_zone(self, current_distance):
        for zone in self.braking_zones:
            if zone['start_dist'] > current_distance:
                return zone
        return self.braking_zones[0] if self.braking_zones else None

    def get_reference_at_distance(self, lap_distance):
        idx = (self.reference['lap_distance'] - lap_distance).abs().idxmin()
        return self.reference.iloc[idx]

    def get_recently_exited_corner(self, current_distance, ignore_turns=None):
        """Return corner data if the car just exited a corner (within 80m past exit)."""
        ignore_turns = ignore_turns or set()
        for zone in self.corners:
            if zone.get('turn_number') in ignore_turns:
                continue
            dist_past_exit = current_distance - zone['exit_dist']
            if 0 < dist_past_exit < 80:
                return zone
        return None

    def calculate_braking_warning_distance(self, current_speed, zone):
        if zone is None:
            return 0
        speed_diff = current_speed - zone['min_speed']
        if speed_diff <= 0:
            return 0

        reaction_time = 0.20
        safety_margin = 10
        reaction_dist = (current_speed / 3.6) * reaction_time
        speed_factor = speed_diff / 150
        extra_margin = speed_factor * 20

        return reaction_dist + safety_margin + extra_margin

    def _build_fallback_corners(self, df):
        """Fallback segmentation using brake spikes when corner extraction is sparse."""
        fallback = []
        in_zone = False
        start_idx = None

        for idx, row in df.iterrows():
            if row['brake_smooth'] > 0.25 and not in_zone:
                in_zone = True
                start_idx = idx
            elif in_zone and row['brake_smooth'] < 0.1:
                end_idx = idx
                in_zone = False
                if start_idx is None or end_idx <= start_idx:
                    continue

                zone_data = df.iloc[start_idx:end_idx]
                if len(zone_data) < 5:
                    continue

                start_dist = float(zone_data['lap_distance'].iloc[0])
                end_dist = float(zone_data['lap_distance'].iloc[-1])
                if end_dist - start_dist < 20:
                    continue

                min_speed_idx = zone_data['speed'].idxmin()
                apex_dist = float(df.loc[min_speed_idx, 'lap_distance'])
                min_speed = float(zone_data['speed'].min())

                post_corner = df.iloc[min_speed_idx:min(min_speed_idx + 120, len(df))]
                throttle_on = None
                for _, sample in post_corner.iterrows():
                    if sample['throttle'] > 0.5:
                        throttle_on = float(sample['lap_distance'])
                        break

                fallback.append({
                    'start_dist': start_dist,
                    'end_dist': end_dist,
                    'exit_dist': end_dist + 45,
                    'entry_speed': float(zone_data['speed'].iloc[0]),
                    'min_speed': min_speed,
                    'min_speed_dist': apex_dist,
                    'min_gear': int(zone_data['gear'].min()),
                    'brake_start_dist': start_dist,
                    'throttle_on_dist': throttle_on,
                })

        fallback.sort(key=lambda z: z['start_dist'])
        return fallback


# =============================================================================
# SMART TTS QUEUE
# =============================================================================
class SmartTTSQueue:
    PRIORITY_CRITICAL = 0
    PRIORITY_HIGH = 1
    PRIORITY_MEDIUM = 2
    PRIORITY_LOW = 3

    def __init__(self):
        self.queue = queue.PriorityQueue()
        self.current_distance = 0
        self.message_counter = 0

    def put(self, message, priority=PRIORITY_MEDIUM, valid_range=200):
        self.message_counter += 1
        if self.queue.qsize() >= 3 and priority >= self.PRIORITY_MEDIUM:
            return False
        self.queue.put((priority, self.message_counter, {
            'message': message,
            'distance': self.current_distance,
            'valid_range': valid_range,
            'timestamp': time.time(),
        }))
        return True

    def get(self, current_distance, timeout=0.1):
        self.current_distance = current_distance
        while True:
            try:
                priority, counter, data = self.queue.get(timeout=timeout)
            except queue.Empty:
                return None

            dist_traveled = abs(current_distance - data['distance'])
            age = time.time() - data['timestamp']
            if dist_traveled > data['valid_range'] or age > 3.0:
                continue
            return data['message']

    def update_distance(self, distance):
        self.current_distance = distance

    def clear(self):
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break


# =============================================================================
# F1 COACH
# =============================================================================
class F1Coach:
    def __init__(self, enable_logging=False, session_info=None):
        print("=" * 70)
        print(f"  {COACH_NAME.upper()} - F1 25 RACE ENGINEER v4.0")
        print("=" * 70)

        self.enable_logging = enable_logging
        self.session_info = session_info

        # Telemetry state
        self.current_lap_distance = 0
        self.last_lap_distance = 0
        self.current_speed = 0
        self.current_gear = 0
        self.current_throttle = 0
        self.current_brake = 0
        self.current_lap_num = -1
        self.current_lap_time = 0
        self.current_delta = 0

        # Position data (for logging)
        self.position_data = {}

        # Lap validity tracking
        self.lap_is_invalid = False
        self.lap_was_invalid = False

        # Penalty/warning tracking
        self.last_warnings = 0
        self.last_corner_warnings = 0
        self.last_penalties = 0

        # Damage tracking
        self.last_fl_wing = 0
        self.last_fr_wing = 0
        self.last_rear_wing = 0
        self.last_floor = 0

        # Crash detection
        self.last_speed = 0
        self.crash_cooldown = 0

        # Lap tracking
        self.current_lap_data = []
        self.completed_laps = {}
        self.reference = None
        self.reference_lap_num = None
        self.reference_lap_time = None
        self.track_analyzer = None

        # Sector tracking (Part 1 & 2)
        self.last_sector = 0
        self.current_sector = 0
        self.best_sector_times = {1: None, 2: None, 3: None}
        self.reference_sector_times = {1: None, 2: None, 3: None}
        self.pending_sector1_time = 0
        self.pending_sector2_time = 0
        self.sector_announced = {1: False, 2: False}

        # Corner feedback tracking (Part 3)
        self.corner_feedback_given = set()
        self.current_lap_corner_data = {}  # {turn_num: {brake_dist, min_speed, throttle_dist}}
        self.corner_tracking_state = {}  # {turn_num: state}
        self.corner_callouts_this_lap = 0
        self.max_corner_callouts_per_lap = MAX_CORNER_CALLOUTS_PER_LAP

        # Time-trial analytics state
        self.reference_bin_times = []
        self.reference_heatmap_points = []
        self.current_lap_bin_times = [None] * HEATMAP_BIN_COUNT
        self.current_segment_deltas = [None] * HEATMAP_BIN_COUNT
        self.last_lap_segment_deltas = []
        self.best_bin_segment_times = [None] * HEATMAP_BIN_COUNT
        self.last_live_bin_index = None
        self.valid_lap_times = []
        self.sector_history = {1: [], 2: [], 3: []}
        self.corner_history = {}  # per-turn rolling metrics
        self.corner_mastery = []
        self.reference_corner_metrics = {}
        self.last_lap_corner_metrics = []
        self.last_time_loss_summary = []
        self.consistency_metrics = _default_analytics_state()['consistency']
        self.profile_history = {
            'peak_brake': [],
            'brake_slope_peak': [],
            'throttle_jerk': [],
            'steer_rate': [],
            'brake_point_diff': [],
        }
        self.driver_profile = {'tags': [], 'stats': {}}
        self.skill_scores = {
            'Braking Precision': 50.0,
            'Throttle Smoothness': 50.0,
            'Corner Exit Quality': 50.0,
            'Consistency': 50.0,
            'Line Adherence': 50.0,
        }
        self.optimal_lap = _default_analytics_state()['optimal_lap']
        self.lap_performance_rows = []
        self.last_report_data = None
        self._last_lap_summary_tts = -1

        # Cooldowns
        self.cooldowns = {
            'brake': {'last_dist': -1000, 'cooldown': 120},
            'brake_warn': {'last_dist': -1000, 'cooldown': 260},
            'gear': {'last_dist': -1000, 'cooldown': 80},
            'throttle': {'last_dist': -1000, 'cooldown': 150},
            'speed': {'last_dist': -1000, 'cooldown': 200},
            'positive': {'last_dist': -1000, 'cooldown': 300},
            'invalid': {'last_dist': -1000, 'cooldown': 300},
            'damage': {'last_dist': -1000, 'cooldown': 500},
            'crash': {'last_dist': -1000, 'cooldown': 200},
            'corner': {'last_dist': -1000, 'cooldown': 200},
            'lap_summary': {'last_dist': -1000, 'cooldown': 500},
        }
        self.last_cue_time = 0
        self.time_cooldown = 0.8

        self.warned_braking_zones = set()

        # TTS
        if TTS_AVAILABLE:
            self.tts_queue = SmartTTSQueue()
            self.tts_running = True
            self.tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
            self.tts_thread.start()
        else:
            self.tts_queue = None
            self.tts_running = False

        # CSV logging
        self.csv_writer = None
        self.csv_handle = None

        if self.enable_logging and self.session_info:
            print(f"  Logging to: {self.session_info['csv_path']}")

        _reset_analytics_shared_state()
        self._sync_shared_performance_state()
        self.speak(say('intro'), force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
        print(f"\n  {COACH_NAME}: Ready. Complete a lap to set baseline.\n")

    def _tts_worker(self):
        while self.tts_running:
            try:
                message = self.tts_queue.get(self.current_lap_distance, timeout=0.1)
                if message is None:
                    continue

                # Try neural voice first (edge-tts, if enabled and installed)
                if _speak_neural(message):
                    continue

                # Fall back to pyttsx3 with soothing settings
                engine = None
                try:
                    engine = pyttsx3.init()
                    _configure_tts_engine(engine)
                    engine.say(message)
                    engine.runAndWait()
                except Exception as e:
                    print(f"  [TTS Error: {e}]")
                finally:
                    if engine:
                        try:
                            engine.stop()
                            del engine
                        except Exception:
                            pass
            except Exception:
                pass

    def speak(self, message, force=False, priority=SmartTTSQueue.PRIORITY_MEDIUM, valid_range=200):
        current_time = time.time()
        if not force and current_time - self.last_cue_time < self.time_cooldown:
            return False

        spoken = False
        if TTS_AVAILABLE and self.tts_queue:
            if self.tts_queue.put(message, priority, valid_range):
                self.last_cue_time = current_time
                print(f"  {COACH_NAME}: {message}")
                spoken = True
        else:
            print(f"  {COACH_NAME}: {message}")
            spoken = True

        if spoken:
            # Push to speech log for phone display
            log = shared_state['speech_log']
            log.append({'text': message, 'ts': current_time})
            # Keep last 50 messages
            if len(log) > 50:
                shared_state['speech_log'] = log[-50:]
            # Emit to phone immediately
            sio = shared_state.get('socketio')
            if sio:
                try:
                    sio.emit('marco_says', {'text': message}, namespace='/')
                except Exception:
                    pass
            return True
        return False

    def _check_cooldown(self, category):
        cd = self.cooldowns.get(category)
        if cd is None:
            return True
        return abs(self.current_lap_distance - cd['last_dist']) >= cd['cooldown']

    def _set_cooldown(self, category):
        if category in self.cooldowns:
            self.cooldowns[category]['last_dist'] = self.current_lap_distance

    def _format_time_speech(self, time_seconds):
        mins = int(time_seconds // 60)
        secs = time_seconds % 60
        whole_secs = int(secs)
        ms = int(round((secs - whole_secs) * 1000))
        if mins > 0:
            return f"{mins} minute {whole_secs} point {ms:03d}"
        return f"{whole_secs} point {ms:03d}"

    def _format_delta_speech(self, delta):
        abs_d = abs(delta)
        whole = int(abs_d)
        ms = int(round((abs_d - whole) * 1000))
        if whole > 0:
            return f"{whole} point {ms:03d}"
        return f"0 point {ms:03d}"

    def _format_delta_speech_simple(self, delta):
        """Natural delta speech: 'plus point 3 4 6' or 'plus 1 point 2'."""
        abs_d = abs(delta)
        prefix = "plus" if delta > 0 else "minus"

        if abs_d >= 1.0:
            # Over 1 second: "plus 1 point 2"
            whole = int(abs_d)
            frac = int(round((abs_d - whole) * 10))
            if frac == 10:
                whole += 1
                frac = 0
            return f"{prefix} {whole} point {frac}"
        else:
            # Under 1 second: "plus point 3 4 6"
            ms = int(round(abs_d * 1000))
            digits = f"{ms:03d}"
            spaced = " ".join(digits)
            return f"{prefix} point {spaced}"

    def _format_sector_time_speech(self, time_seconds):
        """Format sector time for speech: e.g. '28 point 4'."""
        whole = int(time_seconds)
        frac = int(round((time_seconds - whole) * 10))
        if frac == 10:
            whole += 1
            frac = 0
        return f"{whole} point {frac}"

    @staticmethod
    def _clamp(value, lo, hi):
        return max(lo, min(hi, value))

    @staticmethod
    def _stddev(values):
        clean = [float(v) for v in values if v is not None]
        if len(clean) < 2:
            return 0.0
        return float(statistics.pstdev(clean))

    def _time_at_distance(self, df, target_distance):
        if df is None or len(df) == 0:
            return None

        work = df.sort_values('lap_distance')
        distances = work['lap_distance'].tolist()
        times = work['current_lap_time'].tolist()
        if not distances:
            return None

        d = float(target_distance)
        if d <= distances[0]:
            return float(times[0])
        if d >= distances[-1]:
            return float(times[-1])

        idx = bisect.bisect_left(distances, d)
        left_d = float(distances[idx - 1])
        right_d = float(distances[idx])
        left_t = float(times[idx - 1])
        right_t = float(times[idx])
        if right_d <= left_d:
            return right_t
        ratio = (d - left_d) / (right_d - left_d)
        return left_t + ratio * (right_t - left_t)

    def _value_at_distance(self, df, target_distance, column):
        if df is None or len(df) == 0 or column not in df.columns:
            return None

        work = df.sort_values('lap_distance')
        distances = work['lap_distance'].tolist()
        values = work[column].tolist()
        if not distances:
            return None

        d = float(target_distance)
        if d <= distances[0]:
            return float(values[0])
        if d >= distances[-1]:
            return float(values[-1])

        idx = bisect.bisect_left(distances, d)
        left_d = float(distances[idx - 1])
        right_d = float(distances[idx])
        left_v = float(values[idx - 1])
        right_v = float(values[idx])
        if right_d <= left_d:
            return right_v
        ratio = (d - left_d) / (right_d - left_d)
        return left_v + ratio * (right_v - left_v)

    def _build_bin_profile(self, lap_df):
        if lap_df is None or len(lap_df) < 5:
            return [], []

        work = lap_df.sort_values('lap_distance').reset_index(drop=True)
        work = work[work['lap_distance'] >= 0]
        if len(work) < 5:
            return [], []

        track_length = None
        if self.track_analyzer is not None:
            track_length = float(self.track_analyzer.track_length)
        if not track_length or track_length <= 0:
            track_length = float(work['lap_distance'].max())
        if track_length <= 0:
            return [], []

        dedup = work.drop_duplicates(subset=['lap_distance'], keep='first')
        distances = dedup['lap_distance'].tolist()
        times = dedup['current_lap_time'].tolist()
        xs = dedup['pos_x'].tolist() if 'pos_x' in dedup.columns else None
        zs = dedup['pos_z'].tolist() if 'pos_z' in dedup.columns else None

        bin_times = []
        bin_points = []
        for i in range(HEATMAP_BIN_COUNT):
            target = (track_length * i) / max(1, (HEATMAP_BIN_COUNT - 1))

            if target <= distances[0]:
                bin_times.append(float(times[0]))
                if xs is not None and zs is not None:
                    bin_points.append([float(xs[0]), float(zs[0])])
                continue

            if target >= distances[-1]:
                bin_times.append(float(times[-1]))
                if xs is not None and zs is not None:
                    bin_points.append([float(xs[-1]), float(zs[-1])])
                continue

            idx = bisect.bisect_left(distances, target)
            d0 = float(distances[idx - 1])
            d1 = float(distances[idx])
            t0 = float(times[idx - 1])
            t1 = float(times[idx])
            ratio = 1.0 if d1 <= d0 else (target - d0) / (d1 - d0)

            interp_time = t0 + ratio * (t1 - t0)
            bin_times.append(interp_time)

            if xs is not None and zs is not None:
                x0 = float(xs[idx - 1])
                x1 = float(xs[idx])
                z0 = float(zs[idx - 1])
                z1 = float(zs[idx])
                bin_points.append([
                    x0 + ratio * (x1 - x0),
                    z0 + ratio * (z1 - z0),
                ])

        return bin_times, bin_points

    def _cumulative_to_segment_times(self, cumulative_times):
        if not cumulative_times:
            return []
        segments = [None] * len(cumulative_times)
        for i in range(1, len(cumulative_times)):
            prev_t = cumulative_times[i - 1]
            cur_t = cumulative_times[i]
            if prev_t is None or cur_t is None:
                continue
            seg = cur_t - prev_t
            if seg > 0:
                segments[i] = seg
        return segments

    def _update_live_bin_deltas(self):
        if not self.reference_bin_times or self.track_analyzer is None:
            return
        if self.current_lap_distance < 0 or self.current_lap_time <= 0:
            return

        track_length = float(self.track_analyzer.track_length or 0)
        if track_length <= 0:
            return

        ratio = self._clamp(self.current_lap_distance / track_length, 0.0, 1.0)
        idx = int(round(ratio * (HEATMAP_BIN_COUNT - 1)))
        idx = max(0, min(HEATMAP_BIN_COUNT - 1, idx))

        if self.last_live_bin_index is None:
            self.current_lap_bin_times[idx] = self.current_lap_time
            self.last_live_bin_index = idx
        elif idx >= self.last_live_bin_index:
            prev_idx = self.last_live_bin_index
            prev_time = self.current_lap_bin_times[prev_idx]
            self.current_lap_bin_times[idx] = self.current_lap_time
            if prev_time is not None and idx > prev_idx + 1:
                span = idx - prev_idx
                for b in range(prev_idx + 1, idx):
                    frac = (b - prev_idx) / span
                    self.current_lap_bin_times[b] = prev_time + frac * (self.current_lap_time - prev_time)
            self.last_live_bin_index = idx

        for b in range(0, (self.last_live_bin_index or 0) + 1):
            cur_t = self.current_lap_bin_times[b]
            ref_t = self.reference_bin_times[b] if b < len(self.reference_bin_times) else None
            if cur_t is None or ref_t is None:
                continue
            self.current_segment_deltas[b] = cur_t - ref_t

    def _sync_shared_performance_state(self):
        shared_state['reference_bins'] = self.reference_bin_times
        shared_state['current_lap_bins'] = self.current_lap_bin_times
        shared_state['segment_deltas'] = self.current_segment_deltas
        shared_state['last_lap_segment_deltas'] = self.last_lap_segment_deltas
        shared_state['heatmap_points'] = self.reference_heatmap_points
        shared_state['bin_meta'] = {
            'count': HEATMAP_BIN_COUNT,
            'track_length': float(self.track_analyzer.track_length) if self.track_analyzer else 0.0,
        }
        shared_state['corner_metrics'] = self.last_lap_corner_metrics
        shared_state['corner_mastery'] = self.corner_mastery
        shared_state['consistency'] = self.consistency_metrics
        shared_state['driver_profile'] = self.driver_profile
        shared_state['skill_scores'] = self.skill_scores
        shared_state['optimal_lap'] = self.optimal_lap
        shared_state['time_loss_summary'] = self.last_time_loss_summary
        summary = None
        if self.last_report_data:
            summary = {
                'laps_analyzed': self.last_report_data.get('laps_analyzed'),
                'best_skill_area': self.last_report_data.get('best_skill_area'),
                'top_focus': self.last_report_data.get('practice_focuses', [])[:1],
                'generated_at': self.last_report_data.get('generated_at'),
            }
        shared_state['session_report_summary'] = summary

    def _infer_corner_reason(self, metric, reference_metric):
        if not reference_metric:
            return ('none', 'No reference')

        delta = metric.get('delta_vs_ref')
        brake_diff = None
        if metric.get('brake_point') is not None and reference_metric.get('brake_point') is not None:
            brake_diff = metric['brake_point'] - reference_metric['brake_point']
        exit_diff = None
        if metric.get('exit_speed') is not None and reference_metric.get('exit_speed') is not None:
            exit_diff = metric['exit_speed'] - reference_metric['exit_speed']
        apex_diff = None
        if metric.get('apex_speed') is not None and reference_metric.get('apex_speed') is not None:
            apex_diff = metric['apex_speed'] - reference_metric['apex_speed']
        entry_diff = None
        if metric.get('entry_speed') is not None and reference_metric.get('entry_speed') is not None:
            entry_diff = metric['entry_speed'] - reference_metric['entry_speed']

        if brake_diff is not None and brake_diff > BRAKE_POINT_DIFF_M and (delta is None or delta > 0.0):
            return ('brake_earlier', 'Brake earlier')
        if exit_diff is not None and exit_diff < -EXIT_SPEED_DIFF_KPH:
            return ('focus_exit', 'Exit speed low')
        if apex_diff is not None and apex_diff < -APEX_SPEED_DIFF_KPH and (entry_diff is not None and entry_diff > -2.0):
            return ('overslow_apex', 'Over-slowed apex')
        if entry_diff is not None and entry_diff < -ENTRY_SPEED_DIFF_KPH:
            return ('entry_speed', 'Carry more entry speed')
        if metric.get('throttle_point') is not None and reference_metric.get('throttle_point') is not None:
            throttle_diff = metric['throttle_point'] - reference_metric['throttle_point']
            if throttle_diff > THROTTLE_POINT_DIFF_M:
                return ('throttle_late', 'Throttle too late')

        return ('clean', 'Clean corner')

    def _build_corner_callout(self, turn, live_corner, zone):
        if turn not in self.reference_corner_metrics:
            return None

        ref = self.reference_corner_metrics[turn]
        profile_tags = set(self.driver_profile.get('tags', []))
        delta = None
        if self.reference is not None:
            zone_end = min(float(zone['exit_dist']), float(self.track_analyzer.track_length))
            ref_start = self._time_at_distance(self.reference, zone['start_dist'])
            ref_end = self._time_at_distance(self.reference, zone_end)
            cur_start = live_corner.get('entry_time')
            cur_end = live_corner.get('exit_time')
            if ref_start is not None and ref_end is not None and cur_start is not None and cur_end is not None:
                delta = (cur_end - cur_start) - (ref_end - ref_start)

        brake_diff = None
        if live_corner.get('brake_dist') is not None and ref.get('brake_point') is not None:
            brake_diff = live_corner['brake_dist'] - ref['brake_point']
        entry_diff = None
        if live_corner.get('entry_speed') is not None and ref.get('entry_speed') is not None:
            entry_diff = live_corner['entry_speed'] - ref['entry_speed']
        apex_diff = None
        if live_corner.get('min_speed') is not None and ref.get('apex_speed') is not None:
            apex_diff = live_corner['min_speed'] - ref['apex_speed']
        exit_diff = None
        if live_corner.get('exit_speed') is not None and ref.get('exit_speed') is not None:
            exit_diff = live_corner['exit_speed'] - ref['exit_speed']

        if brake_diff is not None and brake_diff > BRAKE_POINT_DIFF_M and (delta is None or delta > 0.0):
            return say('corner_brake_earlier', turn=turn)
        if exit_diff is not None and exit_diff < -EXIT_SPEED_DIFF_KPH:
            return say('corner_focus_exit', turn=turn)
        if 'Aggressive Braker' in profile_tags and apex_diff is not None and apex_diff < -2.0:
            return say('corner_overslow_apex', turn=turn)
        if 'Cautious Braker' in profile_tags and entry_diff is not None and entry_diff < -3.0:
            return say('corner_entry_speed', turn=turn)
        if apex_diff is not None and apex_diff < -APEX_SPEED_DIFF_KPH and (entry_diff is not None and entry_diff > -2.0):
            return say('corner_overslow_apex', turn=turn)
        if entry_diff is not None and entry_diff < -ENTRY_SPEED_DIFF_KPH:
            return say('corner_entry_speed', turn=turn)
        if delta is not None and delta < -0.05:
            return say('corner_good', turn=turn)
        return None

    def _compute_corner_metrics_for_lap(self, lap_df, with_delta=True):
        if self.track_analyzer is None or lap_df is None or len(lap_df) == 0:
            return []

        work = lap_df.sort_values('lap_distance').reset_index(drop=True)
        if len(work) == 0:
            return []

        track_length = float(self.track_analyzer.track_length or work['lap_distance'].max())
        metrics = []

        for zone in self.track_analyzer.corners:
            turn = int(zone['turn_number'])
            start_d = max(0.0, float(zone['start_dist']) - 5.0)
            end_d = min(track_length, float(zone['exit_dist']))
            if end_d <= start_d:
                continue

            seg = work[(work['lap_distance'] >= start_d) & (work['lap_distance'] <= end_d)]
            if len(seg) < 3:
                continue

            entry_speed = self._value_at_distance(work, start_d, 'speed')
            exit_speed = self._value_at_distance(work, end_d, 'speed')

            apex_row = seg.loc[seg['speed'].idxmin()]
            apex_speed = float(apex_row['speed'])
            apex_dist = float(apex_row['lap_distance'])

            brake_search = work[(work['lap_distance'] >= max(0.0, start_d - 80.0)) & (work['lap_distance'] <= end_d)]
            brake_point = None
            braking_rows = brake_search[brake_search['brake'] > 0.25]
            if len(braking_rows) > 0:
                brake_point = float(braking_rows['lap_distance'].iloc[0])

            throttle_point = None
            throttle_search = work[(work['lap_distance'] >= apex_dist) & (work['lap_distance'] <= min(track_length, end_d + 60.0))]
            throttle_rows = throttle_search[(throttle_search['throttle'] > 0.55) & (throttle_search['brake'] < 0.2)]
            if len(throttle_rows) > 0:
                throttle_point = float(throttle_rows['lap_distance'].iloc[0])

            start_time = self._time_at_distance(work, start_d)
            end_time = self._time_at_distance(work, end_d)
            corner_time = None
            if start_time is not None and end_time is not None and end_time >= start_time:
                corner_time = end_time - start_time

            delta_vs_ref = None
            if with_delta and self.reference is not None:
                ref_start = self._time_at_distance(self.reference, start_d)
                ref_end = self._time_at_distance(self.reference, end_d)
                if ref_start is not None and ref_end is not None and start_time is not None and end_time is not None:
                    delta_vs_ref = (end_time - start_time) - (ref_end - ref_start)

            metric = {
                'turn': turn,
                'start_distance': start_d,
                'apex_distance': apex_dist,
                'end_distance': end_d,
                'entry_speed': float(entry_speed) if entry_speed is not None else None,
                'apex_speed': apex_speed,
                'exit_speed': float(exit_speed) if exit_speed is not None else None,
                'brake_point': brake_point,
                'throttle_point': throttle_point,
                'corner_time': float(corner_time) if corner_time is not None else None,
                'delta_vs_ref': float(delta_vs_ref) if delta_vs_ref is not None else None,
                'reason': 'none',
                'reason_label': 'No reference',
            }

            ref_metric = self.reference_corner_metrics.get(turn)
            reason_key, reason_label = self._infer_corner_reason(metric, ref_metric)
            metric['reason'] = reason_key
            metric['reason_label'] = reason_label
            metrics.append(metric)

        return metrics

    def _update_corner_mastery(self, corner_metrics):
        for metric in corner_metrics:
            turn = metric['turn']
            history = self.corner_history.setdefault(turn, {
                'entry': [],
                'apex': [],
                'exit': [],
                'delta': [],
                'brake': [],
            })

            history['entry'].append(metric.get('entry_speed'))
            history['apex'].append(metric.get('apex_speed'))
            history['exit'].append(metric.get('exit_speed'))
            history['delta'].append(metric.get('delta_vs_ref'))
            history['brake'].append(metric.get('brake_point'))

            for key in history:
                if len(history[key]) > CORNER_HISTORY_WINDOW:
                    history[key] = history[key][-CORNER_HISTORY_WINDOW:]

        mastery = []
        for turn, hist in sorted(self.corner_history.items()):
            deltas = [d for d in hist['delta'] if d is not None]
            if not deltas:
                continue

            mean_delta = float(sum(deltas) / len(deltas))
            sigma = self._stddev(deltas[-CONSISTENCY_WINDOW_LAPS:])

            pace_score = self._clamp(100.0 - max(0.0, mean_delta) * 260.0, 0.0, 100.0)
            consistency_score = self._clamp(100.0 - sigma * 420.0, 0.0, 100.0)
            score = 0.65 * pace_score + 0.35 * consistency_score

            trend = 0.0
            if len(deltas) >= 6:
                prev = sum(deltas[-6:-3]) / 3.0
                recent = sum(deltas[-3:]) / 3.0
                trend = prev - recent

            mastery.append({
                'turn': int(turn),
                'score': round(score, 1),
                'avg_delta': round(mean_delta, 4),
                'consistency_sigma': round(sigma, 4),
                'trend': round(trend, 4),
            })

        self.corner_mastery = mastery

    def _update_consistency_metrics(self):
        recent_laps = self.valid_lap_times[-CONSISTENCY_WINDOW_LAPS:]
        lap_sigma = self._stddev(recent_laps)

        s1_sigma = self._stddev(self.sector_history[1][-CONSISTENCY_WINDOW_LAPS:])
        s2_sigma = self._stddev(self.sector_history[2][-CONSISTENCY_WINDOW_LAPS:])
        s3_sigma = self._stddev(self.sector_history[3][-CONSISTENCY_WINDOW_LAPS:])

        corner_sigmas = []
        brake_sigmas = []
        for turn, hist in self.corner_history.items():
            dvals = [d for d in hist['delta'] if d is not None][-CONSISTENCY_WINDOW_LAPS:]
            if dvals:
                corner_sigmas.append({'turn': turn, 'sigma': self._stddev(dvals)})
            bvals = [b for b in hist['brake'] if b is not None][-CONSISTENCY_WINDOW_LAPS:]
            if len(bvals) >= 2:
                brake_sigmas.append(self._stddev(bvals))

        most_inconsistent = max(corner_sigmas, key=lambda c: c['sigma']) if corner_sigmas else None
        most_consistent = min(corner_sigmas, key=lambda c: c['sigma']) if corner_sigmas else None
        braking_sigma = (sum(brake_sigmas) / len(brake_sigmas)) if brake_sigmas else None

        self.consistency_metrics = {
            'lap_sigma': round(lap_sigma, 4) if lap_sigma else 0.0,
            'sector_sigma': {
                's1': round(s1_sigma, 4) if s1_sigma else 0.0,
                's2': round(s2_sigma, 4) if s2_sigma else 0.0,
                's3': round(s3_sigma, 4) if s3_sigma else 0.0,
            },
            'most_inconsistent_corner': {
                'turn': int(most_inconsistent['turn']),
                'sigma': round(most_inconsistent['sigma'], 4),
            } if most_inconsistent else None,
            'most_consistent_corner': {
                'turn': int(most_consistent['turn']),
                'sigma': round(most_consistent['sigma'], 4),
            } if most_consistent else None,
            'braking_point_sigma': round(braking_sigma, 4) if braking_sigma is not None else None,
        }

    def _update_driver_profile(self, lap_df, corner_metrics):
        work = lap_df.sort_values('current_lap_time')
        if len(work) < 5:
            return

        peak_brake = float(work['brake'].max())
        throttle_vals = work['throttle'].tolist()
        brake_vals = work['brake'].tolist()
        times = work['current_lap_time'].tolist()
        steer_vals = work['steer'].tolist() if 'steer' in work.columns else []

        brake_slopes = []
        throttle_changes = []
        steer_rates = []
        for i in range(1, len(work)):
            dt = max(0.001, float(times[i] - times[i - 1]))
            brake_slopes.append((float(brake_vals[i]) - float(brake_vals[i - 1])) / dt)
            throttle_changes.append(float(throttle_vals[i]) - float(throttle_vals[i - 1]))
            if steer_vals:
                steer_rates.append(abs(float(steer_vals[i]) - float(steer_vals[i - 1])) / dt)

        brake_slope_peak = max(brake_slopes) if brake_slopes else 0.0
        throttle_jerk = self._stddev(throttle_changes)
        steer_rate = self._stddev(steer_rates) if steer_rates else 0.0

        brake_diffs = []
        for metric in corner_metrics:
            ref = self.reference_corner_metrics.get(metric['turn'])
            if not ref:
                continue
            if metric.get('brake_point') is None or ref.get('brake_point') is None:
                continue
            brake_diffs.append(metric['brake_point'] - ref['brake_point'])
        brake_point_diff = (sum(brake_diffs) / len(brake_diffs)) if brake_diffs else 0.0

        history = getattr(self, 'profile_history', None)
        if history is None:
            self.profile_history = {
                'peak_brake': [],
                'brake_slope_peak': [],
                'throttle_jerk': [],
                'steer_rate': [],
                'brake_point_diff': [],
            }
            history = self.profile_history

        history['peak_brake'].append(peak_brake)
        history['brake_slope_peak'].append(brake_slope_peak)
        history['throttle_jerk'].append(throttle_jerk)
        history['steer_rate'].append(steer_rate)
        history['brake_point_diff'].append(brake_point_diff)
        for key in history:
            if len(history[key]) > CORNER_HISTORY_WINDOW:
                history[key] = history[key][-CORNER_HISTORY_WINDOW:]

        avg_peak = sum(history['peak_brake']) / len(history['peak_brake'])
        avg_slope = sum(history['brake_slope_peak']) / len(history['brake_slope_peak'])
        avg_jerk = sum(history['throttle_jerk']) / len(history['throttle_jerk'])
        avg_turn_in = sum(history['steer_rate']) / len(history['steer_rate']) if history['steer_rate'] else 0.0
        avg_brake_diff = sum(history['brake_point_diff']) / len(history['brake_point_diff'])

        tags = []
        if avg_peak > 0.90 and avg_slope > 2.5:
            tags.append('Aggressive Braker')
        if avg_brake_diff < -8.0:
            tags.append('Cautious Braker')
        elif avg_brake_diff > 8.0:
            tags.append('Late Braker')
        if avg_jerk < 0.045:
            tags.append('Smooth Throttle')
        elif avg_jerk > 0.10:
            tags.append('Abrupt Throttle')
        if avg_turn_in > 2.2:
            tags.append('Sharp Turn-In')

        self.driver_profile = {
            'tags': tags,
            'stats': {
                'braking_aggressiveness': round(avg_peak * 100.0, 2),
                'brake_slope_peak': round(avg_slope, 3),
                'throttle_jerk': round(avg_jerk, 4),
                'turn_in_rate': round(avg_turn_in, 4),
                'brake_point_bias_m': round(avg_brake_diff, 3),
            },
        }

    def _update_skill_scores(self, corner_metrics):
        brake_diffs = []
        exit_losses = []
        throttle_delays = []
        apex_losses = []

        for metric in corner_metrics:
            ref = self.reference_corner_metrics.get(metric['turn'])
            if not ref:
                continue

            if metric.get('brake_point') is not None and ref.get('brake_point') is not None:
                brake_diffs.append(metric['brake_point'] - ref['brake_point'])
            if metric.get('exit_speed') is not None and ref.get('exit_speed') is not None:
                exit_losses.append(max(0.0, ref['exit_speed'] - metric['exit_speed']))
            if metric.get('throttle_point') is not None and ref.get('throttle_point') is not None:
                throttle_delays.append(max(0.0, metric['throttle_point'] - ref['throttle_point']))
            if metric.get('apex_speed') is not None and ref.get('apex_speed') is not None:
                apex_losses.append(max(0.0, ref['apex_speed'] - metric['apex_speed']))

        brake_abs_mean = sum(abs(v) for v in brake_diffs) / len(brake_diffs) if brake_diffs else 18.0
        brake_sigma = self._stddev(brake_diffs)
        braking_precision = self._clamp(100.0 - brake_abs_mean * 2.3 - brake_sigma * 1.4, 0.0, 100.0)

        throttle_jerk = self.driver_profile.get('stats', {}).get('throttle_jerk', 0.08)
        throttle_smoothness = self._clamp(100.0 - throttle_jerk * 650.0, 0.0, 100.0)

        exit_loss = (sum(exit_losses) / len(exit_losses)) if exit_losses else 10.0
        throttle_delay = (sum(throttle_delays) / len(throttle_delays)) if throttle_delays else 20.0
        corner_exit_quality = self._clamp(100.0 - exit_loss * 3.2 - throttle_delay * 1.2, 0.0, 100.0)

        lap_sigma = self.consistency_metrics.get('lap_sigma') or 0.0
        corner_sigma_vals = [c['consistency_sigma'] for c in self.corner_mastery] if self.corner_mastery else []
        mean_corner_sigma = (sum(corner_sigma_vals) / len(corner_sigma_vals)) if corner_sigma_vals else 0.0
        consistency_score = self._clamp(100.0 - lap_sigma * 140.0 - mean_corner_sigma * 180.0, 0.0, 100.0)

        apex_loss = (sum(apex_losses) / len(apex_losses)) if apex_losses else 8.0
        steer_rate = self.driver_profile.get('stats', {}).get('turn_in_rate', 1.0)
        line_adherence = self._clamp(100.0 - apex_loss * 2.5 - steer_rate * 6.0, 0.0, 100.0)

        self.skill_scores = {
            'Braking Precision': round(braking_precision, 1),
            'Throttle Smoothness': round(throttle_smoothness, 1),
            'Corner Exit Quality': round(corner_exit_quality, 1),
            'Consistency': round(consistency_score, 1),
            'Line Adherence': round(line_adherence, 1),
        }

    def _update_optimal_lap(self, lap_bin_times):
        sectors_best = None
        if all(self.best_sector_times.get(i) is not None for i in (1, 2, 3)):
            sectors_best = sum(self.best_sector_times[i] for i in (1, 2, 3))

        if lap_bin_times:
            lap_segments = self._cumulative_to_segment_times(lap_bin_times)
            if lap_segments:
                for i in range(1, min(len(lap_segments), len(self.best_bin_segment_times))):
                    seg = lap_segments[i]
                    if seg is None or seg <= 0:
                        continue
                    best = self.best_bin_segment_times[i]
                    if best is None or seg < best:
                        self.best_bin_segment_times[i] = seg

        bins_best = None
        usable_segments = [s for s in self.best_bin_segment_times[1:] if s is not None]
        if len(usable_segments) >= int(0.9 * (HEATMAP_BIN_COUNT - 1)):
            bins_best = sum(usable_segments)

        gain_sector = None
        gain_bins = None
        if self.reference_lap_time is not None:
            if sectors_best is not None:
                gain_sector = self.reference_lap_time - sectors_best
            if bins_best is not None:
                gain_bins = self.reference_lap_time - bins_best

        self.optimal_lap = {
            'sectors_best': round(sectors_best, 3) if sectors_best is not None else None,
            'bins_best': round(bins_best, 3) if bins_best is not None else None,
            'gain_vs_pb_sectors': round(gain_sector, 3) if gain_sector is not None else None,
            'gain_vs_pb_bins': round(gain_bins, 3) if gain_bins is not None else None,
        }

    def _build_time_loss_summary(self, corner_metrics):
        losses = [m for m in corner_metrics if m.get('delta_vs_ref') is not None and m['delta_vs_ref'] > 0.01]
        losses.sort(key=lambda m: m['delta_vs_ref'], reverse=True)
        summary = []
        for metric in losses[:3]:
            summary.append({
                'turn': int(metric['turn']),
                'delta': round(float(metric['delta_vs_ref']), 3),
                'reason': metric.get('reason_label', 'Time loss'),
            })
        return summary

    def _print_time_loss_summary(self, summary):
        if not summary:
            print("  Time-loss summary: clean lap, no major corner losses")
            return
        print("  Top Time Losses:")
        for item in summary:
            print(f"   - T{item['turn']}: +{item['delta']:.3f}s ({item['reason']})")

    def _maybe_speak_time_loss_summary(self, lap_num, summary):
        if not summary:
            return
        if lap_num == self._last_lap_summary_tts:
            return
        top = summary[0]
        if top['delta'] < 0.12:
            return
        if not self._check_cooldown('lap_summary'):
            return
        delta_speech = self._format_delta_speech_simple(top['delta'])
        self.speak(
            say('lap_time_loss_summary', turn=top['turn'], delta=delta_speech),
            priority=SmartTTSQueue.PRIORITY_MEDIUM,
            valid_range=250,
        )
        self._set_cooldown('lap_summary')
        self._last_lap_summary_tts = lap_num

    def _generate_performance_report(self, final=False):
        rows = [r for r in self.lap_performance_rows if r.get('corner_metrics')]
        if not rows:
            return None

        corner_loss_acc = {}
        for row in rows:
            for metric in row['corner_metrics']:
                d = metric.get('delta_vs_ref')
                if d is None:
                    continue
                turn = metric['turn']
                bucket = corner_loss_acc.setdefault(turn, [])
                bucket.append(d)

        avg_losses = []
        for turn, vals in corner_loss_acc.items():
            if not vals:
                continue
            avg = sum(vals) / len(vals)
            if avg > 0:
                avg_losses.append({'turn': turn, 'avg_delta': avg})
        avg_losses.sort(key=lambda x: x['avg_delta'], reverse=True)

        most_improved = None
        improvement_rows = []
        for turn, vals in corner_loss_acc.items():
            if len(vals) < 4:
                continue
            half = len(vals) // 2
            first = sum(vals[:half]) / max(1, half)
            second = sum(vals[half:]) / max(1, len(vals) - half)
            gain = first - second
            improvement_rows.append({'turn': turn, 'gain': gain})
        if improvement_rows:
            most_improved = max(improvement_rows, key=lambda x: x['gain'])

        best_skill = max(self.skill_scores.items(), key=lambda kv: kv[1])[0] if self.skill_scores else None

        practice_focuses = []
        if len(rows) < 3:
            practice_focuses.append("Need 3 to 5 valid laps for reliable trend analysis")
        for loss in avg_losses[:3]:
            turn = loss['turn']
            reason = None
            for row in reversed(rows):
                for metric in row['corner_metrics']:
                    if metric['turn'] == turn and metric.get('reason_label'):
                        reason = metric['reason_label']
                        break
                if reason:
                    break
            practice_focuses.append(f"Turn {turn}: {reason or 'reduce corner delta'}")
        if best_skill:
            practice_focuses.append(f"Keep leveraging your {best_skill.lower()}")

        report = {
            'generated_at': datetime.now().isoformat(timespec='seconds'),
            'final': bool(final),
            'laps_analyzed': len(rows),
            'biggest_time_loss_corners': [
                {'turn': int(x['turn']), 'avg_delta': round(float(x['avg_delta']), 4)}
                for x in avg_losses[:5]
            ],
            'most_improved_corner': (
                {'turn': int(most_improved['turn']), 'delta_gain': round(float(most_improved['gain']), 4)}
                if most_improved else None
            ),
            'best_skill_area': best_skill,
            'practice_focuses': practice_focuses[:3],
            'driver_profile_tags': self.driver_profile.get('tags', []),
            'skill_scores': self.skill_scores,
            'consistency': self.consistency_metrics,
            'optimal_lap': self.optimal_lap,
        }

        self.last_report_data = report

        if self.enable_logging and self.session_info and self.session_info.get('path'):
            base = self.session_info['path']
            json_path = os.path.join(base, 'performance_report.json')
            md_path = os.path.join(base, 'performance_report.md')
            try:
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(report, f, indent=2)
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write("# Session Performance Report\n\n")
                    f.write(f"- Generated: {report['generated_at']}\n")
                    f.write(f"- Laps analyzed: {report['laps_analyzed']}\n")
                    if report['best_skill_area']:
                        f.write(f"- Best skill area: {report['best_skill_area']}\n")
                    if report['most_improved_corner']:
                        f.write(
                            f"- Most improved corner: Turn {report['most_improved_corner']['turn']} "
                            f"({report['most_improved_corner']['delta_gain']:+.3f}s)\n"
                        )
                    f.write("\n## Biggest Time Loss Corners\n")
                    for item in report['biggest_time_loss_corners'][:3]:
                        f.write(f"- Turn {item['turn']}: +{item['avg_delta']:.3f}s avg\n")
                    f.write("\n## Practice Focuses\n")
                    for item in report['practice_focuses']:
                        f.write(f"- {item}\n")
            except Exception as exc:
                print(f"  [Report save warning: {exc}]")

        shared_state['session_report_summary'] = {
            'laps_analyzed': report.get('laps_analyzed'),
            'best_skill_area': report.get('best_skill_area'),
            'top_focus': report.get('practice_focuses', [])[:1],
            'generated_at': report.get('generated_at'),
        }

        return report

    def _build_post_session_summary_speech(self, report):
        """Build short engineer-style spoken debrief from report data."""
        if not report:
            return None

        laps = int(report.get('laps_analyzed') or 0)
        if laps <= 1:
            return "Session summary. Only one timed lap. Run at least three for a reliable debrief."

        sentences = []

        losses = report.get('biggest_time_loss_corners') or []
        if losses:
            bands = []
            for item in losses[:3]:
                turn = item.get('turn')
                ref_metric = self.reference_corner_metrics.get(turn) if turn is not None else None
                apex_speed = ref_metric.get('apex_speed') if ref_metric else None
                if apex_speed is None:
                    continue
                if apex_speed < 120:
                    bands.append('low-speed')
                elif apex_speed < 190:
                    bands.append('medium-speed')
                else:
                    bands.append('high-speed')

            if bands:
                counts = {}
                for band in bands:
                    counts[band] = counts.get(band, 0) + 1
                top_band = max(counts.items(), key=lambda x: x[1])[0]
                sentences.append(f"You lost most time in {top_band} corners.")
            else:
                top_turn = losses[0].get('turn')
                sentences.append(f"Most time was lost around turn {top_turn}.")
        else:
            sentences.append("No single corner dominated your time loss.")

        improved = report.get('most_improved_corner')
        if improved and improved.get('delta_gain') is not None and improved['delta_gain'] > 0.04:
            sentences.append(f"Brake stability improved in turn {improved['turn']}.")

        focuses = report.get('practice_focuses') or []
        if focuses:
            focus_text = str(focuses[0]).replace(':', ',')
            sentences.append(f"Biggest gain opportunity: {focus_text.lower()}.")
        elif report.get('best_skill_area'):
            skill = str(report['best_skill_area']).lower()
            sentences.append(f"Best skill area today was {skill}.")

        return " ".join(sentences[:3])

    def _check_lap_validity(self, is_invalid):
        if is_invalid and not self.lap_was_invalid:
            self.lap_is_invalid = True
            self.lap_was_invalid = True
            if self._check_cooldown('invalid'):
                self.speak(say('lap_invalidated'), force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
                self._set_cooldown('invalid')
        self.lap_is_invalid = is_invalid

    def _check_crash(self):
        if self.crash_cooldown > 0:
            self.crash_cooldown -= 1
            return
        if not self._check_cooldown('crash'):
            return

        speed_drop = self.last_speed - self.current_speed
        if speed_drop > 80 and self.current_brake < 0.3:
            self.speak(say('crash_heavy'), force=True, priority=SmartTTSQueue.PRIORITY_CRITICAL)
            self._set_cooldown('crash')
            self.crash_cooldown = 60
        elif speed_drop > 40 and self.current_brake < 0.3:
            self.speak(say('crash_light'), priority=SmartTTSQueue.PRIORITY_HIGH)
            self._set_cooldown('crash')
            self.crash_cooldown = 30

    def _check_damage(self, fl_wing, fr_wing, rear_wing, floor):
        if not self._check_cooldown('damage'):
            return

        max_front = max(fl_wing, fr_wing)
        last_max_front = max(self.last_fl_wing, self.last_fr_wing)

        if max_front > last_max_front + 10:
            if max_front > 50:
                self.speak(say('damage_front_wing_heavy'), force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
            elif max_front > 20:
                self.speak(say('damage_front_wing_light'), priority=SmartTTSQueue.PRIORITY_MEDIUM)
            self._set_cooldown('damage')
        elif rear_wing > self.last_rear_wing + 10:
            self.speak(say('damage_rear_wing'), priority=SmartTTSQueue.PRIORITY_HIGH)
            self._set_cooldown('damage')
        elif floor > self.last_floor + 15:
            self.speak(say('damage_floor'), priority=SmartTTSQueue.PRIORITY_MEDIUM)
            self._set_cooldown('damage')

        self.last_fl_wing = fl_wing
        self.last_fr_wing = fr_wing
        self.last_rear_wing = rear_wing
        self.last_floor = floor

    def _check_penalties(self, total_warnings, corner_warnings, penalties):
        if corner_warnings > self.last_corner_warnings:
            self.speak(say('penalty_corner_cutting'), priority=SmartTTSQueue.PRIORITY_MEDIUM)
        elif total_warnings > self.last_warnings:
            self.speak(say('penalty_warning'), priority=SmartTTSQueue.PRIORITY_MEDIUM)

        if penalties > self.last_penalties:
            diff = penalties - self.last_penalties
            self.speak(say('penalty_time', seconds=diff), force=True, priority=SmartTTSQueue.PRIORITY_HIGH)

        self.last_warnings = total_warnings
        self.last_corner_warnings = corner_warnings
        self.last_penalties = penalties

    def handle_event(self, event_code):
        if event_code == b'COLL':
            if self._check_cooldown('crash'):
                self.speak(say('collision_car'), force=True, priority=SmartTTSQueue.PRIORITY_CRITICAL)
                self._set_cooldown('crash')

    def _announce_sector(self, sector_num, sector_time):
        """Announce sector time with color coding and delta."""
        if sector_time <= 0 or self.lap_is_invalid:
            return

        time_speech = self._format_sector_time_speech(sector_time)
        best = self.best_sector_times[sector_num]
        ref = self.reference_sector_times[sector_num]

        sector_color = None

        # Determine color
        if best is None or sector_time < best:
            # Purple - personal best sector
            sector_color = 'purple'
            self.best_sector_times[sector_num] = sector_time
            self.speak(
                say('sector_purple', sector=sector_num, time=time_speech),
                force=True, priority=SmartTTSQueue.PRIORITY_HIGH
            )
        elif ref is not None and sector_time < ref:
            # Green - faster than reference but not PB
            sector_color = 'green'
            self.speak(
                say('sector_green', sector=sector_num, time=time_speech),
                force=True, priority=SmartTTSQueue.PRIORITY_HIGH
            )
        elif ref is not None:
            # Yellow - slower than reference
            sector_color = 'yellow'
            delta = sector_time - ref
            delta_speech = self._format_delta_speech_simple(delta)
            self.speak(
                say('sector_yellow', sector=sector_num, delta=delta_speech),
                force=True, priority=SmartTTSQueue.PRIORITY_HIGH
            )
        else:
            # No reference yet, just announce the time
            self.speak(
                f"Sector {sector_num}, {time_speech}",
                force=True, priority=SmartTTSQueue.PRIORITY_HIGH
            )

        # Update sector color in shared state for phone
        shared_state['sector_colors'][sector_num] = sector_color
        sio = shared_state.get('socketio')
        if sio:
            try:
                sio.emit('sector_color', {
                    'sector': sector_num,
                    'color': sector_color,
                }, namespace='/')
            except Exception:
                pass

        # Announce overall delta after sector callout (Part 1)
        if self.track_analyzer and abs(self.current_delta) > 0.1:
            delta_speech = self._format_delta_speech_simple(self.current_delta)
            if self.current_delta > 0:
                self.speak(say('delta_plus', delta=delta_speech), priority=SmartTTSQueue.PRIORITY_MEDIUM)
            else:
                self.speak(say('delta_minus', delta=delta_speech), priority=SmartTTSQueue.PRIORITY_MEDIUM)

    def _check_sector_change(self, sector, sector1_time, sector2_time):
        """Announce S1/S2 once per lap as soon as telemetry reports valid split times."""
        if sector != self.last_sector:
            self.last_sector = sector

        if not self.sector_announced[1] and sector1_time > 0:
            self.pending_sector1_time = sector1_time
            self._announce_sector(1, sector1_time)
            self.sector_announced[1] = True

        if self.sector_announced[1] and not self.sector_announced[2] and sector2_time > 0:
            self.pending_sector2_time = sector2_time
            self._announce_sector(2, sector2_time)
            self.sector_announced[2] = True

    def _finish_lap(self, lap_num, lap_time):
        if not self.current_lap_data or lap_time <= 0:
            return

        time_speech = self._format_time_speech(lap_time)
        mins = int(lap_time // 60)
        secs = lap_time % 60

        # Mandatory full lap-time callout before any lap summary.
        self.speak(
            f"Lap {lap_num}, {time_speech}",
            force=True,
            priority=SmartTTSQueue.PRIORITY_HIGH
        )

        # S3: just update best/reference tracking silently (lap time callout handles it)
        if self.pending_sector1_time > 0 and self.pending_sector2_time > 0:
            s3_time = lap_time - self.pending_sector1_time - self.pending_sector2_time
            if s3_time > 0:
                best = self.best_sector_times[3]
                ref = self.reference_sector_times[3]
                sector3_color = None
                if best is None or s3_time < best:
                    sector3_color = 'purple'
                    self.best_sector_times[3] = s3_time
                elif ref is not None and s3_time < ref:
                    sector3_color = 'green'
                elif ref is not None:
                    sector3_color = 'yellow'

                if sector3_color is not None:
                    shared_state['sector_colors'][3] = sector3_color
                    sio = shared_state.get('socketio')
                    if sio:
                        try:
                            sio.emit('sector_color', {
                                'sector': 3,
                                'color': sector3_color,
                            }, namespace='/')
                        except Exception:
                            pass

        if self.lap_is_invalid:
            # Update shared state for web interface
            shared_state['lap_times'].append({
                'lap_num': lap_num,
                'time': lap_time,
                'valid': False,
                'is_pb': False,
            })
            self.last_lap_corner_metrics = []
            self.last_time_loss_summary = []
            self.last_lap_segment_deltas = []
            self._sync_shared_performance_state()
            self._emit_lap_update()
            print(f"\n  Lap {lap_num} INVALID - not using as reference\n")
            self.lap_was_invalid = False
            return

        lap_df = pd.DataFrame(self.current_lap_data)
        self.completed_laps[lap_num] = {'time': lap_time, 'data': lap_df}

        is_pb = False
        if self.reference is None or lap_time < self.reference_lap_time:
            is_pb = True
            old_ref = self.reference_lap_time
            self.reference = lap_df
            self.reference_lap_num = lap_num
            self.reference_lap_time = lap_time
            shared_state['fastest_lap'] = {'lap_num': lap_num, 'time': lap_time}
            self.track_analyzer = TrackAnalyzer(self.reference)

            # Update reference sector times from this lap
            if self.pending_sector1_time > 0:
                self.reference_sector_times[1] = self.pending_sector1_time
            if self.pending_sector2_time > 0:
                self.reference_sector_times[2] = self.pending_sector2_time
            if self.pending_sector1_time > 0 and self.pending_sector2_time > 0:
                s3_ref = lap_time - self.pending_sector1_time - self.pending_sector2_time
                if s3_ref > 0:
                    self.reference_sector_times[3] = s3_ref

            # Update track outline for web interface from reference lap
            if 'pos_x' in lap_df.columns and 'pos_z' in lap_df.columns:
                shared_state['track_outline'] = lap_df[['pos_x', 'pos_z']].values.tolist()
                shared_state['_building_outline'] = []  # Stop building, we have reference

            # Save reference lap if logging
            if self.enable_logging and self.session_info:
                self.reference.to_csv(self.session_info['reference_path'], index=False)

            # Build bin reference (cumulative times at fixed distance bins)
            ref_bins, ref_points = self._build_bin_profile(self.reference)
            if ref_bins:
                self.reference_bin_times = ref_bins
                if not self.best_bin_segment_times or len(self.best_bin_segment_times) != HEATMAP_BIN_COUNT:
                    self.best_bin_segment_times = [None] * HEATMAP_BIN_COUNT
            if ref_points:
                self.reference_heatmap_points = ref_points

            # Build reference corner metrics used for per-corner comparisons
            reference_corner_list = self._compute_corner_metrics_for_lap(self.reference, with_delta=False)
            self.reference_corner_metrics = {m['turn']: m for m in reference_corner_list}

            print(f"\n{'='*70}")
            print(f"  FASTEST LAP! Lap {lap_num} - {mins}:{secs:06.3f}")
            print(f"{'='*70}\n")

            if old_ref is None:
                self.speak(say('baseline_set', time=time_speech), force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
            else:
                delta_speech = self._format_delta_speech(old_ref - lap_time)
                self.speak(say('purple_lap', time=time_speech, delta=delta_speech), force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
        else:
            delta = lap_time - self.reference_lap_time
            delta_speech = self._format_delta_speech(delta)
            print(f"\n  Lap {lap_num}: {mins}:{secs:06.3f} (+{delta:.3f}s)\n")

            if delta < 0.5:
                self.speak(say('lap_close', time=time_speech, delta=delta_speech), force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
            elif delta < 2.0:
                self.speak(say('lap_ok', time=time_speech, delta=delta_speech), force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
            else:
                self.speak(say('lap_slow', time=time_speech, delta=delta_speech), force=True, priority=SmartTTSQueue.PRIORITY_HIGH)

        # Build lap-level TT metrics
        if self.pending_sector1_time > 0:
            self.sector_history[1].append(self.pending_sector1_time)
            if len(self.sector_history[1]) > 50:
                self.sector_history[1] = self.sector_history[1][-50:]
        if self.pending_sector2_time > 0:
            self.sector_history[2].append(self.pending_sector2_time)
            if len(self.sector_history[2]) > 50:
                self.sector_history[2] = self.sector_history[2][-50:]
        if self.pending_sector1_time > 0 and self.pending_sector2_time > 0:
            s3_time_for_stats = lap_time - self.pending_sector1_time - self.pending_sector2_time
            if s3_time_for_stats > 0:
                self.sector_history[3].append(s3_time_for_stats)
                if len(self.sector_history[3]) > 50:
                    self.sector_history[3] = self.sector_history[3][-50:]

        self.valid_lap_times.append(lap_time)
        if len(self.valid_lap_times) > 100:
            self.valid_lap_times = self.valid_lap_times[-100:]

        # Compare this lap against reference at fixed distance bins
        lap_bins, _ = self._build_bin_profile(lap_df)
        if lap_bins and self.reference_bin_times:
            lap_deltas = [None] * HEATMAP_BIN_COUNT
            for i in range(min(len(lap_bins), len(self.reference_bin_times), HEATMAP_BIN_COUNT)):
                if lap_bins[i] is None or self.reference_bin_times[i] is None:
                    continue
                lap_deltas[i] = lap_bins[i] - self.reference_bin_times[i]
            self.last_lap_segment_deltas = lap_deltas
        self._update_optimal_lap(lap_bins)

        # Corner metrics + time loss finder
        corner_metrics = self._compute_corner_metrics_for_lap(lap_df, with_delta=True)
        for metric in corner_metrics:
            if metric.get('delta_vs_ref') is not None:
                metric['delta_vs_ref'] = round(metric['delta_vs_ref'], 4)
            for key in ('entry_speed', 'apex_speed', 'exit_speed', 'corner_time'):
                if metric.get(key) is not None:
                    metric[key] = round(metric[key], 3)
            for key in ('start_distance', 'apex_distance', 'end_distance', 'brake_point', 'throttle_point'):
                if metric.get(key) is not None:
                    metric[key] = round(metric[key], 2)
        self.last_lap_corner_metrics = corner_metrics

        time_loss_summary = self._build_time_loss_summary(corner_metrics)
        self.last_time_loss_summary = time_loss_summary
        self._print_time_loss_summary(time_loss_summary)
        self._maybe_speak_time_loss_summary(lap_num, time_loss_summary)

        # Session mastery + consistency + profile + skills
        self._update_corner_mastery(corner_metrics)
        self._update_consistency_metrics()
        self._update_driver_profile(lap_df, corner_metrics)
        self._update_skill_scores(corner_metrics)
        self._sync_shared_performance_state()

        self.lap_performance_rows.append({
            'lap_num': lap_num,
            'lap_time': lap_time,
            'is_pb': is_pb,
            'time_loss_summary': time_loss_summary,
            'corner_metrics': corner_metrics,
        })
        if len(self.lap_performance_rows) > 100:
            self.lap_performance_rows = self.lap_performance_rows[-100:]

        if lap_num % REPORT_INTERVAL_LAPS == 0:
            self._generate_performance_report(final=False)

        # Update shared state for web interface
        shared_state['lap_times'].append({
            'lap_num': lap_num,
            'time': lap_time,
            'valid': True,
            'is_pb': is_pb,
        })
        self._emit_lap_update()

    def _emit_lap_update(self):
        """Emit lap update to web clients."""
        sio = shared_state.get('socketio')
        if sio:
            try:
                sio.emit('lap_update', {
                    'laps': shared_state['lap_times'],
                    'fastest_lap': shared_state['fastest_lap'],
                    'sector_colors': shared_state['sector_colors'],
                    'time_loss_summary': shared_state['time_loss_summary'],
                    'corner_mastery': shared_state['corner_mastery'],
                    'consistency': shared_state['consistency'],
                    'driver_profile': shared_state['driver_profile'],
                    'skill_scores': shared_state['skill_scores'],
                    'optimal_lap': shared_state['optimal_lap'],
                    'segment_deltas': shared_state['segment_deltas'],
                    'last_lap_segment_deltas': shared_state['last_lap_segment_deltas'],
                    'heatmap_points': shared_state['heatmap_points'],
                }, namespace='/')
            except Exception:
                pass

    def calculate_delta(self):
        if self.track_analyzer is None or self.current_lap_distance < 100:
            return 0
        ref = self.track_analyzer.get_reference_at_distance(self.current_lap_distance)
        return self.current_lap_time - ref['current_lap_time']

    def analyze_and_coach(self):
        if self.track_analyzer is None or self.current_lap_distance < 50:
            return

        self.current_delta = self.calculate_delta()
        if self.tts_queue:
            self.tts_queue.update_distance(self.current_lap_distance)

        self._check_braking_zones()
        self._check_gear()
        self._check_throttle()
        self._check_speed()
        self._check_corners()
        # NOTE: _check_delta() removed - delta now announced per sector only

    def _check_braking_zones(self):
        next_zone = self.track_analyzer.get_next_braking_zone(self.current_lap_distance)
        if next_zone is None:
            return

        distance_to_zone = next_zone['start_dist'] - self.current_lap_distance
        if distance_to_zone < 0:
            distance_to_zone += self.track_analyzer.track_length

        warning_dist = self.track_analyzer.calculate_braking_warning_distance(self.current_speed, next_zone)
        zone_id = f"{next_zone['start_dist']:.0f}"

        if 90 < distance_to_zone < 115 and zone_id not in self.warned_braking_zones and self._check_cooldown('brake_warn'):
            # Keep this to big stops only to reduce chatter.
            speed_threshold = max(next_zone['min_speed'] + 75, 170)
            if self.current_speed > speed_threshold:
                self.speak(say('brake_warning'), priority=SmartTTSQueue.PRIORITY_MEDIUM, valid_range=70)
                self.warned_braking_zones.add(zone_id)
                self._set_cooldown('brake_warn')
                return

        if 0 < distance_to_zone < warning_dist and self._check_cooldown('brake'):
            if self.current_throttle > 0.3 and self.current_brake < 0.2:
                if next_zone['min_gear'] < self.current_gear - 1:
                    self.speak(say('brake_with_gear', gear=next_zone['min_gear']), priority=SmartTTSQueue.PRIORITY_CRITICAL, valid_range=60)
                else:
                    self.speak(say('brake_now'), priority=SmartTTSQueue.PRIORITY_CRITICAL, valid_range=60)
                self._set_cooldown('brake')

    def _check_gear(self):
        if not self._check_cooldown('gear'):
            return
        ref = self.track_analyzer.get_reference_at_distance(self.current_lap_distance)
        ref_gear = int(ref['gear'])
        if self.current_gear > ref_gear + 1:
            self.speak(say('downshift', gear=ref_gear), priority=SmartTTSQueue.PRIORITY_HIGH, valid_range=80)
            self._set_cooldown('gear')

    def _check_throttle(self):
        if not self._check_cooldown('throttle'):
            return
        ref = self.track_analyzer.get_reference_at_distance(self.current_lap_distance)
        if ref['throttle'] > 0.8 and self.current_throttle < 0.3 and self.current_brake < 0.1:
            self.speak(say('get_on_power'), priority=SmartTTSQueue.PRIORITY_MEDIUM, valid_range=80)
            self._set_cooldown('throttle')

    def _check_speed(self):
        if not self._check_cooldown('speed'):
            return
        ref = self.track_analyzer.get_reference_at_distance(self.current_lap_distance)
        speed_diff = self.current_speed - ref['speed']

        if speed_diff < -15 and self.current_speed < 200:
            self.speak(say('carry_more_speed'), priority=SmartTTSQueue.PRIORITY_LOW, valid_range=120)
            self._set_cooldown('speed')
        elif speed_diff > 10 and ref['speed'] < 200 and self._check_cooldown('positive'):
            self.speak(say('good_speed'), priority=SmartTTSQueue.PRIORITY_LOW, valid_range=80)
            self._set_cooldown('positive')

    def _check_corners(self):
        """Corner-by-corner TT feedback with per-corner and per-lap callout caps."""
        if self.track_analyzer is None:
            return

        dist = self.current_lap_distance
        if self.current_lap_time <= 0:
            return

        for zone in self.track_analyzer.corners:
            turn = int(zone['turn_number'])
            corner_data = self.current_lap_corner_data.setdefault(turn, {
                'started': False,
                'completed': False,
                'entry_speed': None,
                'entry_time': None,
                'brake_dist': None,
                'min_speed': None,
                'min_speed_dist': None,
                'throttle_dist': None,
                'exit_speed': None,
                'exit_time': None,
            })

            start_d = float(zone['start_dist'])
            end_d = min(float(zone['exit_dist']), float(self.track_analyzer.track_length))

            if not corner_data['started'] and dist >= max(0.0, start_d - 5.0):
                corner_data['started'] = True
                corner_data['entry_speed'] = self.current_speed
                corner_data['entry_time'] = self.current_lap_time

            if not corner_data['started'] or corner_data['completed']:
                continue

            if (
                corner_data['brake_dist'] is None
                and dist >= max(0.0, start_d - 80.0)
                and dist <= end_d
                and self.current_brake > 0.25
            ):
                corner_data['brake_dist'] = dist

            if start_d <= dist <= end_d:
                if corner_data['min_speed'] is None or self.current_speed < corner_data['min_speed']:
                    corner_data['min_speed'] = self.current_speed
                    corner_data['min_speed_dist'] = dist

            if (
                corner_data['min_speed_dist'] is not None
                and corner_data['throttle_dist'] is None
                and dist > corner_data['min_speed_dist']
                and self.current_throttle > 0.55
                and self.current_brake < 0.2
            ):
                corner_data['throttle_dist'] = dist

            if dist > end_d:
                corner_data['completed'] = True
                corner_data['exit_speed'] = self.current_speed
                corner_data['exit_time'] = self.current_lap_time

                if turn in self.corner_feedback_given:
                    continue
                self.corner_feedback_given.add(turn)

                if self.corner_callouts_this_lap >= self.max_corner_callouts_per_lap:
                    continue
                if not self._check_cooldown('corner'):
                    continue

                feedback = self._build_corner_callout(turn, corner_data, zone)
                if feedback:
                    self.speak(feedback, priority=SmartTTSQueue.PRIORITY_MEDIUM, valid_range=160)
                    self.corner_callouts_this_lap += 1
                    self._set_cooldown('corner')

    def _log_telemetry(self, row):
        if not self.enable_logging or not self.session_info:
            return

        if self.csv_writer is None:
            self.csv_handle = open(self.session_info['csv_path'], 'w', newline='')
            self.csv_writer = csv.DictWriter(self.csv_handle, fieldnames=row.keys())
            self.csv_writer.writeheader()

        self.csv_writer.writerow(row)

    def update_position(self, pos_x, pos_y, pos_z, vel_x, vel_y, vel_z):
        self.position_data = {
            'pos_x': pos_x, 'pos_y': pos_y, 'pos_z': pos_z,
            'vel_x': vel_x, 'vel_y': vel_y, 'vel_z': vel_z,
        }
        # Update shared state for web interface
        shared_state['position'] = {'x': pos_x, 'z': pos_z}

        # Build track outline progressively if we don't have one yet
        if not shared_state['track_outline'] and (pos_x != 0 or pos_z != 0):
            # Only add point if it's far enough from the last one (avoid duplicates)
            outline = shared_state.get('_building_outline', [])
            if not outline or (abs(pos_x - outline[-1][0]) > 5 or abs(pos_z - outline[-1][1]) > 5):
                outline.append([pos_x, pos_z])
                shared_state['_building_outline'] = outline
                # Update the live outline every 20 points
                if len(outline) % 20 == 0:
                    shared_state['track_outline'] = list(outline)

    def update_telemetry(self, speed, throttle, brake, gear, steer, engine_rpm, drs,
                         lap_distance, lap_num, current_lap_time, last_lap_time,
                         sector, sector1_time, sector2_time, session_time, frame_id,
                         lap_invalid=0, total_warnings=0, corner_warnings=0, penalties=0):

        # New lap detection
        if lap_num != self.current_lap_num:
            if self.current_lap_num > 0 and last_lap_time > 0:
                self._finish_lap(self.current_lap_num, last_lap_time)

            self.current_lap_num = lap_num
            self.current_lap_data = []
            self.warned_braking_zones.clear()
            self.lap_is_invalid = False
            self.lap_was_invalid = False
            self.last_sector = 0
            self.pending_sector1_time = 0
            self.pending_sector2_time = 0
            self.sector_announced = {1: False, 2: False}
            self.corner_feedback_given.clear()
            self.current_lap_corner_data.clear()
            self.corner_tracking_state.clear()
            self.corner_callouts_this_lap = 0
            self.current_lap_bin_times = [None] * HEATMAP_BIN_COUNT
            self.current_segment_deltas = [None] * HEATMAP_BIN_COUNT
            self.last_live_bin_index = None
            shared_state['sector_colors'] = {1: None, 2: None, 3: None}

            for cd in self.cooldowns.values():
                cd['last_dist'] = -1000
            if self.tts_queue:
                self.tts_queue.clear()

            if lap_num == 0:
                self.speak(say('formation_lap'), force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
            elif lap_num >= 1:
                if self.reference is None:
                    self.speak(say('lap_start_no_ref', lap=lap_num), force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
                else:
                    target = self._format_time_speech(self.reference_lap_time)
                    self.speak(say('lap_start_with_ref', lap=lap_num, target=target), force=True, priority=SmartTTSQueue.PRIORITY_HIGH)

        self.last_speed = self.current_speed
        self.last_lap_distance = self.current_lap_distance
        self.current_lap_distance = lap_distance
        self.current_speed = speed
        self.current_gear = gear
        self.current_throttle = throttle
        self.current_brake = brake
        self.current_lap_time = current_lap_time
        self.current_sector = sector

        # Sector change detection (Part 1 & 2)
        self._check_sector_change(sector, sector1_time, sector2_time)

        self._check_lap_validity(lap_invalid == 1)
        self._check_penalties(total_warnings, corner_warnings, penalties)
        self._check_crash()

        # Record sample
        if lap_num > 0:
            sample = {
                'lap_distance': lap_distance,
                'current_lap_time': current_lap_time,
                'speed': speed,
                'throttle': throttle,
                'brake': brake,
                'gear': gear,
                'steer': steer,
            }
            # Include position data if available
            if self.position_data:
                sample['pos_x'] = self.position_data.get('pos_x', 0)
                sample['pos_z'] = self.position_data.get('pos_z', 0)
            self.current_lap_data.append(sample)

        # Log to CSV
        if self.enable_logging:
            row = {
                'session_time': session_time,
                'frame_id': frame_id,
                'speed': speed,
                'throttle': throttle,
                'steer': steer,
                'brake': brake,
                'gear': gear,
                'engine_rpm': engine_rpm,
                'drs': drs,
                **self.position_data,
                'last_lap_time': last_lap_time,
                'current_lap_time': current_lap_time,
                'sector1_time': sector1_time,
                'sector2_time': sector2_time,
                'lap_distance': lap_distance,
                'current_lap_num': lap_num,
                'sector': sector,
                'lap_invalid': lap_invalid,
            }
            self._log_telemetry(row)

        self.analyze_and_coach()
        self._update_live_bin_deltas()
        self._sync_shared_performance_state()

        # Update shared state for web interface
        shared_state['current_speed'] = speed
        shared_state['current_gear'] = gear
        shared_state['current_lap_num'] = lap_num
        shared_state['current_lap_time'] = current_lap_time
        shared_state['current_delta'] = self.current_delta
        shared_state['current_sector'] = sector

        # Status print every 200m
        if int(self.current_lap_distance / 200) != int(self.last_lap_distance / 200):
            invalid_str = " [INVALID]" if self.lap_is_invalid else ""
            delta_str = f" | ÃŽâ€: {self.current_delta:+.2f}s" if self.track_analyzer else ""
            label = "Out" if lap_num == 0 else f"L{lap_num}"
            print(f"  {label} | {self.current_lap_distance:4.0f}m | {self.current_speed:3.0f} km/h | G{self.current_gear}{delta_str}{invalid_str}")

    def update_damage(self, fl_wing, fr_wing, rear_wing, floor):
        self._check_damage(fl_wing, fr_wing, rear_wing, floor)

    def shutdown(self):
        self.tts_running = False
        if hasattr(self, 'tts_thread') and self.tts_thread.is_alive():
            self.tts_thread.join(timeout=2)
        if self.csv_handle:
            self.csv_handle.close()
            print(f"  Telemetry saved to: {self.session_info['csv_path']}")


# =============================================================================
# UDP RECEIVER
# =============================================================================
def run_coaching_session(enable_logging=False):
    """Run a live coaching session."""
    session_mgr = SessionManager()
    session_info = None

    if enable_logging:
        session_info = session_mgr.create_new_session()
        print(f"\n  Created session folder: {session_info['folder']}")

    coach = F1Coach(enable_logging=enable_logging, session_info=session_info)
    shared_state['coach'] = coach
    shared_state['session_active'] = True
    shared_state['current_mode'] = 2 if enable_logging else 1
    _reset_analytics_shared_state()

    # Clear stale stop requests from prior sessions.
    while True:
        try:
            shared_state['stop_queue'].get_nowait()
        except queue.Empty:
            break

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    sock.settimeout(1.0)

    print(f"\n  Listening on {UDP_IP}:{UDP_PORT}")
    print("  Waiting for F1 25 telemetry...")
    print("  Press Ctrl+C to stop\n")

    packet_count = 0
    last_lap_distance = None
    crossed_start_finish = False
    lap_data = {}
    session_time = 0
    frame_id = 0

    try:
        while True:
            # Check for stop command from phone
            try:
                shared_state['stop_queue'].get_nowait()
                print("\n  [Stop command received from phone]")
                break
            except queue.Empty:
                pass

            try:
                data, addr = sock.recvfrom(4096)
                packet_count += 1

                if len(data) >= HEADER_SIZE:
                    header = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
                    packet_id = header[5]
                    session_time = header[7]
                    frame_id = header[8]
                    player_car_index = header[10]

                    # Motion packet (ID 0)
                    if packet_id == 0:
                        offset = HEADER_SIZE + (player_car_index * 60)
                        if len(data) >= offset + 24:
                            motion = struct.unpack('<ffffff', data[offset:offset+24])
                            coach.update_position(*motion)

                    # Lap data packet (ID 2)
                    elif packet_id == 2:
                        offset = HEADER_SIZE + (player_car_index * LAP_DATA_SIZE)
                        if len(data) >= offset + LAP_DATA_SIZE:
                            lap = struct.unpack(LAP_DATA_FMT, data[offset:offset + LAP_DATA_SIZE])

                            lap_distance = lap[10]
                            raw_lap_num = int(lap[14])
                            lap_invalid = lap[18]
                            penalties = lap[19]
                            total_warnings = lap[20]
                            corner_warnings = lap[21]

                            if last_lap_distance is not None and last_lap_distance < 0 and lap_distance >= 0:
                                if not crossed_start_finish:
                                    crossed_start_finish = True
                                    print(f"\n  >>> START/FINISH - LAP 1 <<<\n")

                            current_lap_num = 0 if not crossed_start_finish else raw_lap_num
                            last_lap_distance = lap_distance

                            lap_data = {
                                'lap_distance': lap_distance,
                                'current_lap_num': current_lap_num,
                                'current_lap_time': lap[1] / 1000.0,
                                'last_lap_time': lap[0] / 1000.0,
                                'sector1_time': (lap[3] * 60.0) + (lap[2] / 1000.0),
                                'sector2_time': (lap[5] * 60.0) + (lap[4] / 1000.0),
                                'sector': lap[17],
                                'lap_invalid': lap_invalid,
                                'total_warnings': total_warnings,
                                'corner_warnings': corner_warnings,
                                'penalties': penalties,
                            }

                    # Event packet (ID 3)
                    elif packet_id == 3:
                        if len(data) >= HEADER_SIZE + 4:
                            event_code = data[HEADER_SIZE:HEADER_SIZE + 4]
                            coach.handle_event(event_code)

                    # Car telemetry packet (ID 6)
                    elif packet_id == 6:
                        offset = HEADER_SIZE + (player_car_index * CAR_TELEM_SIZE)
                        if len(data) >= offset + CAR_TELEM_SIZE:
                            car = struct.unpack(CAR_TELEM_FMT, data[offset:offset + CAR_TELEM_SIZE])

                            if lap_data:
                                coach.update_telemetry(
                                    speed=car[0],
                                    throttle=car[1],
                                    brake=car[3],
                                    gear=car[5],
                                    steer=car[2],
                                    engine_rpm=car[6],
                                    drs=car[7],
                                    lap_distance=lap_data['lap_distance'],
                                    lap_num=lap_data['current_lap_num'],
                                    current_lap_time=lap_data['current_lap_time'],
                                    last_lap_time=lap_data['last_lap_time'],
                                    sector=lap_data['sector'],
                                    sector1_time=lap_data['sector1_time'],
                                    sector2_time=lap_data['sector2_time'],
                                    session_time=session_time,
                                    frame_id=frame_id,
                                    lap_invalid=lap_data.get('lap_invalid', 0),
                                    total_warnings=lap_data.get('total_warnings', 0),
                                    corner_warnings=lap_data.get('corner_warnings', 0),
                                    penalties=lap_data.get('penalties', 0),
                                )

                    # Car damage packet (ID 10)
                    elif packet_id == 10:
                        damage_per_car = 42
                        offset = HEADER_SIZE + (player_car_index * damage_per_car)
                        damage_offset = offset + 20

                        if len(data) >= damage_offset + 4:
                            damage_data = struct.unpack('<BBBB', data[damage_offset:damage_offset + 4])
                            coach.update_damage(
                                fl_wing=damage_data[0],
                                fr_wing=damage_data[1],
                                rear_wing=damage_data[2],
                                floor=damage_data[3],
                            )

                # Flush CSV periodically
                if enable_logging and coach.csv_handle and packet_count % 100 == 0:
                    coach.csv_handle.flush()

            except socket.timeout:
                pass

    except KeyboardInterrupt:
        pass

    print(f"\n\n{'='*70}")
    print(f"  {COACH_NAME}: {say('session_end')}")
    print(f"{'='*70}")
    print(f"  Packets: {packet_count:,}")
    if coach.completed_laps:
        print(f"  Valid laps: {len(coach.completed_laps)}")
        print(f"  Fastest: Lap {coach.reference_lap_num} - {coach.reference_lap_time:.3f}s")

    report = coach._generate_performance_report(final=True)
    if report and coach.enable_logging and coach.session_info and coach.session_info.get('path'):
        print(f"  Report: {os.path.join(coach.session_info['path'], 'performance_report.json')}")

    post_summary = coach._build_post_session_summary_speech(report)
    if post_summary:
        coach.speak(post_summary, force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
        time.sleep(0.5)

    coach.speak(say('session_end'), force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
    time.sleep(2)
    coach.shutdown()
    sock.close()

    shared_state['session_active'] = False
    shared_state['current_mode'] = None
    shared_state['coach'] = None
    shared_state['lap_times'] = []
    shared_state['track_outline'] = []
    shared_state['position'] = {'x': 0, 'z': 0}
    shared_state['current_speed'] = 0
    shared_state['current_gear'] = 0
    shared_state['current_lap_num'] = 0
    shared_state['current_lap_time'] = 0
    shared_state['current_delta'] = 0
    shared_state['current_sector'] = 0
    shared_state['fastest_lap'] = None
    shared_state['sector_colors'] = {1: None, 2: None, 3: None}
    shared_state['speech_log'] = []
    _reset_analytics_shared_state()


# =============================================================================
# SESSION ANALYSIS
# =============================================================================
def analyze_session(session_path):
    """Analyze a recorded session."""
    csv_path = os.path.join(session_path, 'telemetry.csv')

    print(f"\n  Loading: {csv_path}")
    df = pd.read_csv(csv_path)
    print(f"  Loaded {len(df):,} telemetry points\n")

    all_laps = sorted(df['current_lap_num'].unique())
    racing_laps = [l for l in all_laps if l >= 1]

    if 0 in all_laps:
        pts = len(df[df['current_lap_num'] == 0])
        print(f"  Formation lap (Lap 0): {pts} points - skipping\n")

    if not racing_laps:
        print("  No racing laps found!")
        return None

    print("=" * 70)
    print("  LAP ANALYSIS")
    print("=" * 70)

    lap_info = []

    for lap_num in racing_laps:
        lap_df = df[df['current_lap_num'] == lap_num]

        next_lap_df = df[df['current_lap_num'] == lap_num + 1]
        if len(next_lap_df) > 0:
            lap_time = next_lap_df['last_lap_time'].iloc[0]
            is_complete = lap_time > 0
        else:
            lap_time = lap_df['current_lap_time'].max() if len(lap_df) > 0 else 0
            is_complete = False

        was_invalid = False
        if 'lap_invalid' in lap_df.columns:
            was_invalid = lap_df['lap_invalid'].max() > 0

        max_speed = lap_df['speed'].max()
        avg_speed = lap_df['speed'].mean()

        lap_info.append({
            'lap_num': lap_num,
            'points': len(lap_df),
            'lap_time': lap_time,
            'max_speed': max_speed,
            'avg_speed': avg_speed,
            'is_complete': is_complete,
            'was_invalid': was_invalid,
        })

        status = "COMPLETE" if is_complete else "INCOMPLETE"
        if was_invalid:
            status = "INVALID"

        print(f"  Lap {lap_num:2d} | {lap_time:7.3f}s | {len(lap_df):5d} pts | "
              f"Max: {max_speed:3.0f} km/h | Avg: {avg_speed:3.0f} km/h | {status}")

    valid_complete = [l for l in lap_info if l['is_complete'] and not l['was_invalid']]

    if not valid_complete:
        print("\n  No valid complete laps found!")
        return df, lap_info, None

    fastest = min(valid_complete, key=lambda x: x['lap_time'])

    print("\n" + "=" * 70)
    print(f"  FASTEST VALID LAP: Lap {fastest['lap_num']} - {fastest['lap_time']:.3f}s")
    print("=" * 70)

    reference_df = df[df['current_lap_num'] == fastest['lap_num']].copy()
    reference_df = reference_df.sort_values('lap_distance').reset_index(drop=True)

    ref_path = os.path.join(session_path, 'reference_lap.csv')
    reference_df.to_csv(ref_path, index=False)
    print(f"\n  Reference lap saved: {ref_path}")

    return df, lap_info, fastest


def plot_session(df, lap_info, fastest_lap_num, session_path, show=True):
    """Generate visualization plots."""
    if not PLOTTING_AVAILABLE:
        print("  matplotlib not available - skipping plots")
        return

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    colors = plt.cm.tab10(np.linspace(0, 1, 10))

    ax1 = axes[0, 0]
    for i, lap in enumerate(lap_info):
        lap_num = lap['lap_num']
        lap_df = df[df['current_lap_num'] == lap_num]

        if lap['is_complete'] and not lap['was_invalid'] and 'pos_x' in lap_df.columns:
            lw = 2.5 if lap_num == fastest_lap_num else 1.5
            alpha = 1.0 if lap_num == fastest_lap_num else 0.6
            label = f"Lap {lap_num} ({lap['lap_time']:.3f}s)" + (" *" if lap_num == fastest_lap_num else "")
            ax1.plot(lap_df['pos_x'], lap_df['pos_z'], color=colors[i % 10], linewidth=lw, alpha=alpha, label=label)

    ax1.set_xlabel('X Position (m)')
    ax1.set_ylabel('Z Position (m)')
    ax1.set_title('Track Map')
    ax1.legend(loc='best', fontsize=8)
    ax1.grid(True, alpha=0.3)
    ax1.set_aspect('equal')

    ax2 = axes[0, 1]
    for i, lap in enumerate(lap_info):
        lap_num = lap['lap_num']
        lap_df = df[df['current_lap_num'] == lap_num]

        if lap['is_complete'] and not lap['was_invalid']:
            lw = 2.5 if lap_num == fastest_lap_num else 1.5
            alpha = 1.0 if lap_num == fastest_lap_num else 0.6
            ax2.plot(lap_df['lap_distance'], lap_df['speed'], color=colors[i % 10], linewidth=lw, alpha=alpha)

    ax2.set_xlabel('Lap Distance (m)')
    ax2.set_ylabel('Speed (km/h)')
    ax2.set_title('Speed Trace')
    ax2.grid(True, alpha=0.3)

    ax3 = axes[1, 0]
    if fastest_lap_num:
        fastest_df = df[df['current_lap_num'] == fastest_lap_num]
        ax3.plot(fastest_df['lap_distance'], fastest_df['throttle'], 'g-', lw=1.5, label='Throttle')
        ax3.plot(fastest_df['lap_distance'], fastest_df['brake'], 'r-', lw=1.5, label='Brake')
        ax3.fill_between(fastest_df['lap_distance'], 0, fastest_df['throttle'], color='green', alpha=0.3)
        ax3.fill_between(fastest_df['lap_distance'], 0, fastest_df['brake'], color='red', alpha=0.3)
    ax3.set_xlabel('Lap Distance (m)')
    ax3.set_ylabel('Input (0-1)')
    ax3.set_title(f'Throttle & Brake - Lap {fastest_lap_num}')
    ax3.legend()
    ax3.grid(True, alpha=0.3)
    ax3.set_ylim(-0.1, 1.1)

    ax4 = axes[1, 1]
    if fastest_lap_num:
        fastest_df = df[df['current_lap_num'] == fastest_lap_num]
        ax4.plot(fastest_df['lap_distance'], fastest_df['gear'], 'b-', lw=2)
        ax4.fill_between(fastest_df['lap_distance'], 0, fastest_df['gear'], color='blue', alpha=0.3)
    ax4.set_xlabel('Lap Distance (m)')
    ax4.set_ylabel('Gear')
    ax4.set_title(f'Gear Selection - Lap {fastest_lap_num}')
    ax4.grid(True, alpha=0.3)
    ax4.set_ylim(0, 9)

    plt.tight_layout()

    output_file = os.path.join(session_path, 'analysis.png')
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"\n  Plot saved: {output_file}")
    if show:
        plt.show()
    plt.close()
    return output_file


# =============================================================================
# MENU SYSTEM
# =============================================================================
def print_menu():
    print("\n")
    print("=" * 60)
    print(f"  {COACH_NAME.upper()} - F1 25 RACE ENGINEER v4.0")
    print("=" * 60)
    print()
    print("  1. Live Coaching Only")
    print("  2. Live Coaching + Telemetry Logging")
    print("  3. Analyze Past Session")
    print("  4. View Track Map from Session")
    print("  5. Exit")
    print()
    print("=" * 60)


def select_session():
    """Let user select a session."""
    session_mgr = SessionManager()
    sessions = session_mgr.get_existing_sessions()

    if not sessions:
        print("\n  No sessions found!")
        return None

    print("\n  Available sessions:")
    print("  " + "-" * 50)

    for i, sess in enumerate(sessions[-10:], 1):
        info = session_mgr.get_session_info(sess['path'])
        if info:
            print(f"  {i}. {sess['folder']} | {info['num_laps']} laps | {info['size_kb']:.1f} KB")
        else:
            print(f"  {i}. {sess['folder']}")

    print("  " + "-" * 50)
    print("  0. Cancel")

    try:
        choice = input("\n  Select session: ").strip()
        if choice == '0' or choice == '':
            return None

        idx = int(choice) - 1
        display_sessions = sessions[-10:]
        if 0 <= idx < len(display_sessions):
            return display_sessions[idx]['path']
    except ValueError:
        pass

    print("  Invalid selection")
    return None



