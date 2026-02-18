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
from datetime import datetime

# Optional imports
try:
    import pyttsx3
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False

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
}


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
    'brake_warning': ["Braking soon", "Big stop coming"],
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

    # Session
    'session_end': ["Good session. See you next time.", "Session complete. Nice work."],
}

def say(category, **kwargs):
    phrases = DIALOGUES.get(category, [category])
    phrase = random.choice(phrases)
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

        for idx, zone in enumerate(self.corners, start=1):
            zone['turn_number'] = idx

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

        # Cooldowns
        self.cooldowns = {
            'brake': {'last_dist': -1000, 'cooldown': 120},
            'gear': {'last_dist': -1000, 'cooldown': 80},
            'throttle': {'last_dist': -1000, 'cooldown': 150},
            'speed': {'last_dist': -1000, 'cooldown': 200},
            'positive': {'last_dist': -1000, 'cooldown': 300},
            'invalid': {'last_dist': -1000, 'cooldown': 300},
            'damage': {'last_dist': -1000, 'cooldown': 500},
            'crash': {'last_dist': -1000, 'cooldown': 200},
            'corner': {'last_dist': -1000, 'cooldown': 200},
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

        self.speak(say('intro'), force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
        print(f"\n  {COACH_NAME}: Ready. Complete a lap to set baseline.\n")

    def _tts_worker(self):
        while self.tts_running:
            try:
                message = self.tts_queue.get(self.current_lap_distance, timeout=0.1)
                if message is None:
                    continue
                engine = None
                try:
                    engine = pyttsx3.init()
                    engine.setProperty('rate', 180)
                    engine.setProperty('volume', 1.0)
                    engine.say(message)
                    engine.runAndWait()
                except Exception as e:
                    print(f"  [TTS Error: {e}]")
                finally:
                    if engine:
                        try:
                            engine.stop()
                            del engine
                        except:
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

        if self.sector_announced[1] and not self.sector_announced[2] and sector2_time > self.pending_sector1_time:
            self.pending_sector2_time = sector2_time
            s2_time = sector2_time - self.pending_sector1_time
            if s2_time > 0:
                self._announce_sector(2, s2_time)
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
        if self.pending_sector2_time > 0:
            s3_time = lap_time - self.pending_sector2_time
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
            if self.pending_sector2_time > 0 and self.pending_sector1_time > 0:
                self.reference_sector_times[2] = self.pending_sector2_time - self.pending_sector1_time
            if self.pending_sector2_time > 0:
                self.reference_sector_times[3] = lap_time - self.pending_sector2_time

            # Update track outline for web interface from reference lap
            if 'pos_x' in lap_df.columns and 'pos_z' in lap_df.columns:
                shared_state['track_outline'] = lap_df[['pos_x', 'pos_z']].values.tolist()
                shared_state['_building_outline'] = []  # Stop building, we have reference

            # Save reference lap if logging
            if self.enable_logging and self.session_info:
                self.reference.to_csv(self.session_info['reference_path'], index=False)

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
        if not self._check_cooldown('brake'):
            return

        next_zone = self.track_analyzer.get_next_braking_zone(self.current_lap_distance)
        if next_zone is None:
            return

        distance_to_zone = next_zone['start_dist'] - self.current_lap_distance
        if distance_to_zone < 0:
            distance_to_zone += self.track_analyzer.track_length

        warning_dist = self.track_analyzer.calculate_braking_warning_distance(self.current_speed, next_zone)
        zone_id = f"{next_zone['start_dist']:.0f}"

        if 80 < distance_to_zone < 120 and zone_id not in self.warned_braking_zones:
            if self.current_speed > next_zone['min_speed'] + 60:
                self.speak(say('brake_warning'), priority=SmartTTSQueue.PRIORITY_HIGH, valid_range=80)
                self.warned_braking_zones.add(zone_id)
                self._set_cooldown('brake')
                return

        if 0 < distance_to_zone < warning_dist:
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
        """Corner-by-corner feedback after exiting each turn."""
        if self.track_analyzer is None:
            return
        if not self._check_cooldown('corner'):
            return

        # Track current corner data as we drive through all detected corners.
        for zone in self.track_analyzer.corners:
            turn = zone['turn_number']
            dist = self.current_lap_distance

            # Initialize tracking for this corner
            if turn not in self.corner_tracking_state:
                self.corner_tracking_state[turn] = 'waiting'

            if turn not in self.current_lap_corner_data:
                self.current_lap_corner_data[turn] = {
                    'brake_dist': None,
                    'min_speed': None,
                    'min_speed_dist': None,
                    'throttle_dist': None,
                }

            corner_data = self.current_lap_corner_data[turn]

            # Detect brake point: first time brake > 0.2 near this corner
            if (corner_data['brake_dist'] is None
                    and zone['start_dist'] - 50 < dist < zone['end_dist']
                    and self.current_brake > 0.2):
                corner_data['brake_dist'] = dist

            # Track min speed through corner
            if zone['start_dist'] < dist < zone['exit_dist']:
                if corner_data['min_speed'] is None or self.current_speed < corner_data['min_speed']:
                    corner_data['min_speed'] = self.current_speed
                    corner_data['min_speed_dist'] = dist

            # Detect throttle application after min speed
            if (corner_data['min_speed_dist'] is not None
                    and corner_data['throttle_dist'] is None
                    and dist > corner_data['min_speed_dist']
                    and self.current_throttle > 0.5):
                corner_data['throttle_dist'] = dist

        # Check if we just exited a corner
        exited = self.track_analyzer.get_recently_exited_corner(
            self.current_lap_distance,
            ignore_turns=self.corner_feedback_given
        )
        if exited is None:
            return

        turn = exited['turn_number']

        corner_data = self.current_lap_corner_data.get(turn)
        if corner_data is None:
            return

        # Check time delta through this corner
        ref_at_exit = self.track_analyzer.get_reference_at_distance(exited['exit_dist'])
        if self.current_lap_time <= 0:
            return

        # Give feedback on EVERY corner (priority: brake > min speed > throttle)
        # If nothing notable, say "Good turn N"
        feedback = None

        # 1. Brake point comparison
        if corner_data['brake_dist'] is not None and exited['brake_start_dist'] is not None:
            brake_diff = corner_data['brake_dist'] - exited['brake_start_dist']
            if brake_diff < -10:
                feedback = say('corner_brake_later', turn=turn)
            elif brake_diff > 10:
                feedback = say('corner_good_brake', turn=turn)

        # 2. Min speed comparison
        if feedback is None and corner_data['min_speed'] is not None:
            speed_diff = corner_data['min_speed'] - exited['min_speed']
            if speed_diff < -5:
                feedback = say('corner_carry_speed', turn=turn)
            elif speed_diff > 5:
                feedback = say('corner_good_speed', turn=turn)

        # 3. Throttle application comparison
        if feedback is None and corner_data['throttle_dist'] is not None and exited['throttle_on_dist'] is not None:
            throttle_diff = corner_data['throttle_dist'] - exited['throttle_on_dist']
            if throttle_diff > 15:
                feedback = say('corner_earlier_throttle', turn=turn)
            elif throttle_diff < -15:
                feedback = say('corner_good_exit', turn=turn)

        # 4. Nothing notable - still give feedback
        if feedback is None:
            feedback = say('corner_good', turn=turn)

        self.speak(feedback, priority=SmartTTSQueue.PRIORITY_MEDIUM, valid_range=150)
        self._set_cooldown('corner')

        self.corner_feedback_given.add(turn)

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
                                'sector1_time': lap[2] / 1000.0,
                                'sector2_time': lap[4] / 1000.0,
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


def plot_session(df, lap_info, fastest_lap_num, session_path):
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
    plt.show()


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



