import socket
import struct
import pandas as pd
import pyttsx3
import time
import threading
import queue
import random

# F1 25 UDP Settings
UDP_IP = "0.0.0.0"
UDP_PORT = 20777

# =============================================================================
# PACKET FORMATS - F1 25
# =============================================================================
HEADER_FMT = '<HBBBBBQfIIBB'
HEADER_SIZE = struct.calcsize(HEADER_FMT)

CAR_TELEM_FMT = '<HfffBbHBBHHHHHBBBBBBBBHffffBBBB'
CAR_TELEM_SIZE = struct.calcsize(CAR_TELEM_FMT)

# Lap Data Packet (ID 2) - F1 25
# Fields: lastLapTimeMS, currentLapTimeMS, sector1MSPart, sector1MinPart,
#         sector2MSPart, sector2MinPart, deltaToFrontMS, deltaToFrontMin,
#         deltaToLeaderMS, deltaToLeaderMin, lapDistance, totalDistance,
#         safetyCarDelta, carPosition, currentLapNum, pitStatus,
#         numPitStops, sector, currentLapInvalid, penalties,
#         totalWarnings, cornerCuttingWarnings, numUnservedDriveThrough,
#         numUnservedStopGo, gridPosition, driverStatus, resultStatus,
#         pitLaneTimerActive, pitLaneTimeInLaneMS, pitStopTimerMS,
#         pitStopShouldServePen, speedTrapFastestSpeed, speedTrapFastestLap
LAP_DATA_FMT = '<IIHBHBHBHBfffBBBBBBBBBBBBBBHHBfB'
LAP_DATA_SIZE = struct.calcsize(LAP_DATA_FMT)

# Car Damage Packet (ID 10) - F1 25
# tyresWear[4](ffff) tyresDamage[4](BBBB) brakesDamage[4](BBBB) tyreBlisters[4](BBBB)
# frontLeftWingDamage(B) frontRightWingDamage(B) rearWingDamage(B)
# floorDamage(B) diffuserDamage(B) sidepodDamage(B) drsFault(B) ersFault(B)
# gearBoxDamage(B) engineDamage(B) + wear fields...
CAR_DAMAGE_FMT = '<ffffBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB'
CAR_DAMAGE_SIZE = struct.calcsize(CAR_DAMAGE_FMT)

COACH_NAME = "Marco"

# Infringement type names from F1 25 UDP spec
INFRINGEMENT_NAMES = {
    3: "collision",
    4: "collision", 
    7: "corner cutting",
    25: "corner cutting",
    26: "running wide",
    27: "corner cutting",
    28: "corner cutting",
    29: "corner cutting",
    30: "wall riding",
    31: "flashback",
    32: "reset to track",
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
    
    # === INVALID LAP RESPONSES ===
    'lap_invalidated': [
        "Lap invalid.",
        "That lap won't count.",
        "Lap deleted.",
    ],
    'lap_invalid_corner_cut': [
        "Track limits. Lap invalid.",
        "Corner cut. Lap's gone.",
        "Exceeded track limits.",
    ],
    'lap_invalid_wall': [
        "Wall contact. Lap invalid.",
        "Touched the barrier. Lap's gone.",
        "Wall riding. Invalid.",
    ],
    'lap_invalid_running_wide': [
        "Ran wide. Lap invalid.",
        "Too wide on exit. Lap deleted.",
        "Off track. Invalid lap.",
    ],
    'lap_invalid_reset': [
        "Reset detected. Lap invalid.",
        "Reset to track. Lap won't count.",
    ],
    'lap_invalid_flashback': [
        "Flashback used. Lap invalid.",
    ],
    
    # === CRASH/COLLISION RESPONSES ===
    'crash_heavy': [
        "Big impact. Check your damage.",
        "That was a heavy one.",
        "Into the barriers. Shake it off.",
        "Heavy contact there.",
    ],
    'crash_light': [
        "Small contact.",
        "Light touch.",
        "Bit of a tap there.",
    ],
    'collision_car': [
        "Contact with another car.",
        "Car collision. Watch the stewards.",
    ],
    
    # === DAMAGE RESPONSES ===
    'damage_front_wing_light': [
        "Minor front wing damage.",
        "Front wing took a hit.",
    ],
    'damage_front_wing_heavy': [
        "Heavy front wing damage. Be careful in corners.",
        "Significant wing damage. You'll lose downforce.",
    ],
    'damage_rear_wing': [
        "Rear wing damage.",
        "Rear wing hit. Watch high speed stability.",
    ],
    'damage_floor': [
        "Floor damage. You'll feel it in the corners.",
    ],
    'damage_sidepod': [
        "Sidepod damage.",
    ],
    
    # === PENALTY RESPONSES ===
    'penalty_warning': [
        "That's a warning. Keep it clean.",
        "Warning from race control.",
    ],
    'penalty_corner_cutting': [
        "Track limits warning.",
        "Corner cutting warning.",
    ],
    'penalty_time': [
        "{seconds} second penalty.",
    ],
    
    # === RECOVERY ===
    'recovery_after_incident': [
        "Okay, focus. Let's recover.",
        "Shake it off. Concentrate.",
        "Put that behind you.",
    ],
    
    # === BRAKING (TUNED - LATER WARNINGS) ===
    'brake_warning': [
        "Braking soon",
        "Big stop coming",
    ],
    'brake_now': [
        "Brake",
        "Brake now",
        "Braking zone",
    ],
    'brake_with_gear': [
        "Brake, {gear}",
        "Brake, down to {gear}",
    ],
    
    # === GEAR COACHING ===
    'downshift': [
        "Down to {gear}",
        "{gear}",
        "Gear {gear}",
    ],
    
    # === THROTTLE COACHING ===
    'get_on_power': [
        "Power",
        "Throttle",
        "On the gas",
    ],
    
    # === SPEED COACHING ===
    'carry_more_speed': [
        "More speed here",
        "Carry more speed",
    ],
    'good_speed': [
        "Good speed",
        "Nice",
    ],
    
    # === DELTA ===
    'delta_plus': [
        "Plus {delta}",
    ],
    'delta_minus': [
        "Minus {delta}",
    ],
    
    # === SESSION ===
    'session_end': [
        "Good session. See you next time.",
        "Session complete. Nice work.",
    ],
}

def say(category, **kwargs):
    """Get a random phrase from a category."""
    phrases = DIALOGUES.get(category, [category])
    phrase = random.choice(phrases)
    return phrase.format(**kwargs) if kwargs else phrase


# =============================================================================
# TRACK ANALYZER - Only braking zones (no acceleration prediction)
# =============================================================================
class TrackAnalyzer:
    """Analyzes reference lap for braking zones only."""
    
    def __init__(self, reference_df):
        self.reference = reference_df.sort_values('lap_distance').reset_index(drop=True)
        self.braking_zones = []
        self.track_length = self.reference['lap_distance'].max()
        self._analyze()
    
    def _analyze(self):
        """Find braking zones from reference lap."""
        df = self.reference.copy()
        df['brake_smooth'] = df['brake'].rolling(window=5, min_periods=1).mean()
        
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
                        self.braking_zones.append({
                            'start_dist': zone_data['lap_distance'].iloc[0],
                            'end_dist': zone_data['lap_distance'].iloc[-1],
                            'entry_speed': zone_data['speed'].iloc[0],
                            'min_speed': zone_data['speed'].min(),
                            'min_gear': int(zone_data['gear'].min()),
                        })
        
        print(f"\n  Track Analysis:")
        print(f"  - Length: {self.track_length:.0f}m")
        print(f"  - Braking zones: {len(self.braking_zones)}")
        for i, z in enumerate(self.braking_zones):
            print(f"    {i+1}: {z['start_dist']:.0f}m | {z['entry_speed']:.0f}->{z['min_speed']:.0f} km/h | G{z['min_gear']}")
    
    def get_next_braking_zone(self, current_distance):
        for zone in self.braking_zones:
            if zone['start_dist'] > current_distance:
                return zone
        return self.braking_zones[0] if self.braking_zones else None
    
    def get_reference_at_distance(self, lap_distance):
        idx = (self.reference['lap_distance'] - lap_distance).abs().idxmin()
        return self.reference.iloc[idx]
    
    def calculate_braking_warning_distance(self, current_speed, zone):
        """Calculate warning distance - TUNED to be later (less early)."""
        if zone is None:
            return 0
        
        speed_diff = current_speed - zone['min_speed']
        if speed_diff <= 0:
            return 0
        
        # TUNED: Reduced values for later warnings
        reaction_time = 0.20   # seconds (was 0.4)
        safety_margin = 10     # meters (was 30)
        
        reaction_dist = (current_speed / 3.6) * reaction_time
        speed_factor = speed_diff / 150
        extra_margin = speed_factor * 20  # was 50
        
        return reaction_dist + safety_margin + extra_margin


# =============================================================================
# SMART TTS QUEUE
# =============================================================================
class SmartTTSQueue:
    PRIORITY_CRITICAL = 0  # Crashes, braking
    PRIORITY_HIGH = 1      # Invalid lap, damage, lap times
    PRIORITY_MEDIUM = 2    # Penalties, gear
    PRIORITY_LOW = 3       # Delta, positive feedback
    
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
# F1 COACH - Main class with crash/invalid/damage detection
# =============================================================================
class F1Coach:
    def __init__(self):
        print("=" * 70)
        print(f"  {COACH_NAME.upper()} - F1 25 RACE ENGINEER v3.0")
        print("  Features: Crash detection, Invalid laps, Damage monitoring")
        print("=" * 70)

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

        # Lap validity tracking
        self.lap_is_invalid = False
        self.lap_was_invalid = False  # To detect transition
        self.last_invalidation_reason = None

        # Penalty/warning tracking
        self.total_warnings = 0
        self.corner_cutting_warnings = 0
        self.penalties = 0
        self.last_warnings = 0
        self.last_corner_warnings = 0
        self.last_penalties = 0

        # Damage tracking
        self.front_left_wing_damage = 0
        self.front_right_wing_damage = 0
        self.rear_wing_damage = 0
        self.floor_damage = 0
        self.sidepod_damage = 0
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

        # Cooldowns per category
        self.cooldowns = {
            'brake': {'last_dist': -1000, 'cooldown': 120},
            'gear': {'last_dist': -1000, 'cooldown': 80},
            'throttle': {'last_dist': -1000, 'cooldown': 150},
            'speed': {'last_dist': -1000, 'cooldown': 200},
            'delta': {'last_dist': -1000, 'cooldown': 400},
            'positive': {'last_dist': -1000, 'cooldown': 300},
            'invalid': {'last_dist': -1000, 'cooldown': 300},
            'damage': {'last_dist': -1000, 'cooldown': 500},
            'crash': {'last_dist': -1000, 'cooldown': 200},
        }
        self.last_cue_time = 0
        self.time_cooldown = 0.8

        # Braking zone tracking
        self.warned_braking_zones = set()

        # TTS
        self.tts_queue = SmartTTSQueue()
        self.tts_running = True
        self.tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
        self.tts_thread.start()

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
            except Exception as e:
                print(f"  [TTS Worker Error: {e}]")

    def speak(self, message, force=False, priority=SmartTTSQueue.PRIORITY_MEDIUM, valid_range=200):
        current_time = time.time()
        if not force and current_time - self.last_cue_time < self.time_cooldown:
            return False
        if self.tts_queue.put(message, priority, valid_range):
            self.last_cue_time = current_time
            print(f"  {COACH_NAME}: {message}")
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

    # =========================================================================
    # INVALID LAP DETECTION
    # =========================================================================
    def _check_lap_validity(self, is_invalid, infringement_type=None):
        """Check if lap just became invalid and announce it."""
        if is_invalid and not self.lap_was_invalid:
            # Lap just became invalid
            self.lap_is_invalid = True
            self.lap_was_invalid = True
            
            if self._check_cooldown('invalid'):
                # Determine reason from infringement type if available
                if infringement_type in [7, 25, 27, 28, 29]:
                    self.speak(say('lap_invalid_corner_cut'), 
                              force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
                elif infringement_type == 30:
                    self.speak(say('lap_invalid_wall'),
                              force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
                elif infringement_type == 26:
                    self.speak(say('lap_invalid_running_wide'),
                              force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
                elif infringement_type == 31:
                    self.speak(say('lap_invalid_flashback'),
                              force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
                elif infringement_type == 32:
                    self.speak(say('lap_invalid_reset'),
                              force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
                else:
                    self.speak(say('lap_invalidated'),
                              force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
                self._set_cooldown('invalid')
        
        self.lap_is_invalid = is_invalid

    # =========================================================================
    # CRASH DETECTION (from sudden speed loss)
    # =========================================================================
    def _check_crash(self):
        """Detect crashes from sudden speed drops."""
        if self.crash_cooldown > 0:
            self.crash_cooldown -= 1
            return
        
        if not self._check_cooldown('crash'):
            return
        
        # Detect sudden deceleration (crash into wall)
        speed_drop = self.last_speed - self.current_speed
        
        # Heavy crash: >80 km/h drop in one frame while not braking
        if speed_drop > 80 and self.current_brake < 0.3:
            self.speak(say('crash_heavy'), force=True, priority=SmartTTSQueue.PRIORITY_CRITICAL)
            self._set_cooldown('crash')
            self.crash_cooldown = 60  # ~1 second cooldown at 60Hz
        # Light contact: >40 km/h drop
        elif speed_drop > 40 and self.current_brake < 0.3:
            self.speak(say('crash_light'), priority=SmartTTSQueue.PRIORITY_HIGH)
            self._set_cooldown('crash')
            self.crash_cooldown = 30

    # =========================================================================
    # DAMAGE DETECTION
    # =========================================================================
    def _check_damage(self, fl_wing, fr_wing, rear_wing, floor, sidepod):
        """Detect new damage."""
        if not self._check_cooldown('damage'):
            return
        
        # Front wing damage
        max_front = max(fl_wing, fr_wing)
        last_max_front = max(self.last_fl_wing, self.last_fr_wing)
        
        if max_front > last_max_front + 10:
            if max_front > 50:
                self.speak(say('damage_front_wing_heavy'), 
                          force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
            elif max_front > 20:
                self.speak(say('damage_front_wing_light'),
                          priority=SmartTTSQueue.PRIORITY_MEDIUM)
            self._set_cooldown('damage')
        
        # Rear wing damage
        elif rear_wing > self.last_rear_wing + 10:
            self.speak(say('damage_rear_wing'), priority=SmartTTSQueue.PRIORITY_HIGH)
            self._set_cooldown('damage')
        
        # Floor damage
        elif floor > self.last_floor + 15:
            self.speak(say('damage_floor'), priority=SmartTTSQueue.PRIORITY_MEDIUM)
            self._set_cooldown('damage')
        
        # Update last values
        self.last_fl_wing = fl_wing
        self.last_fr_wing = fr_wing
        self.last_rear_wing = rear_wing
        self.last_floor = floor

    # =========================================================================
    # PENALTY/WARNING DETECTION
    # =========================================================================
    def _check_penalties(self, total_warnings, corner_warnings, penalties):
        """Check for new penalties or warnings."""
        # New corner cutting warning
        if corner_warnings > self.last_corner_warnings:
            self.speak(say('penalty_corner_cutting'), priority=SmartTTSQueue.PRIORITY_MEDIUM)
        
        # New general warning
        elif total_warnings > self.last_warnings:
            self.speak(say('penalty_warning'), priority=SmartTTSQueue.PRIORITY_MEDIUM)
        
        # New time penalty
        if penalties > self.last_penalties:
            diff = penalties - self.last_penalties
            self.speak(say('penalty_time', seconds=diff), 
                      force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
        
        self.last_warnings = total_warnings
        self.last_corner_warnings = corner_warnings
        self.last_penalties = penalties

    # =========================================================================
    # EVENT HANDLING (collisions, etc.)
    # =========================================================================
    def handle_event(self, event_code, event_data):
        """Handle F1 25 event packets."""
        if event_code == b'COLL':
            # Collision event
            if self._check_cooldown('crash'):
                self.speak(say('collision_car'), force=True, priority=SmartTTSQueue.PRIORITY_CRITICAL)
                self._set_cooldown('crash')

    # =========================================================================
    # LAP COMPLETION
    # =========================================================================
    def _finish_lap(self, lap_num, lap_time):
        if not self.current_lap_data or lap_time <= 0:
            return
        
        # Don't use invalid laps as reference
        if self.lap_is_invalid:
            print(f"\n  Lap {lap_num} was INVALID - not using as reference\n")
            self.lap_was_invalid = False
            return

        lap_df = pd.DataFrame(self.current_lap_data)
        self.completed_laps[lap_num] = {'time': lap_time, 'data': lap_df}

        time_speech = self._format_time_speech(lap_time)
        mins = int(lap_time // 60)
        secs = lap_time % 60

        if self.reference is None or lap_time < self.reference_lap_time:
            old_ref = self.reference_lap_time
            self.reference = lap_df
            self.reference_lap_num = lap_num
            self.reference_lap_time = lap_time
            self.track_analyzer = TrackAnalyzer(self.reference)
            
            print(f"\n{'='*70}")
            print(f"  FASTEST LAP! Lap {lap_num} - {mins}:{secs:06.3f}")
            print(f"{'='*70}\n")

            if old_ref is None:
                self.speak(say('baseline_set', time=time_speech), 
                          force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
            else:
                delta_speech = self._format_delta_speech(old_ref - lap_time)
                self.speak(say('purple_lap', time=time_speech, delta=delta_speech),
                          force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
        else:
            delta = lap_time - self.reference_lap_time
            delta_speech = self._format_delta_speech(delta)
            
            print(f"\n  Lap {lap_num}: {mins}:{secs:06.3f} (+{delta:.3f}s)\n")

            if delta < 0.5:
                self.speak(say('lap_close', time=time_speech, delta=delta_speech),
                          force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
            elif delta < 2.0:
                self.speak(say('lap_ok', time=time_speech, delta=delta_speech),
                          force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
            else:
                self.speak(say('lap_slow', time=time_speech, delta=delta_speech),
                          force=True, priority=SmartTTSQueue.PRIORITY_HIGH)

    # =========================================================================
    # COACHING LOGIC
    # =========================================================================
    def calculate_delta(self):
        if self.track_analyzer is None or self.current_lap_distance < 100:
            return 0
        ref = self.track_analyzer.get_reference_at_distance(self.current_lap_distance)
        return self.current_lap_time - ref['current_lap_time']

    def analyze_and_coach(self):
        if self.track_analyzer is None or self.current_lap_distance < 50:
            return

        self.current_delta = self.calculate_delta()
        self.tts_queue.update_distance(self.current_lap_distance)

        self._check_braking_zones()
        self._check_gear()
        self._check_throttle()
        self._check_speed()
        self._check_delta()

    def _check_braking_zones(self):
        """Predictive braking - TUNED for later warnings."""
        if not self._check_cooldown('brake'):
            return

        next_zone = self.track_analyzer.get_next_braking_zone(self.current_lap_distance)
        if next_zone is None:
            return

        distance_to_zone = next_zone['start_dist'] - self.current_lap_distance
        if distance_to_zone < 0:
            distance_to_zone += self.track_analyzer.track_length

        warning_dist = self.track_analyzer.calculate_braking_warning_distance(
            self.current_speed, next_zone
        )

        zone_id = f"{next_zone['start_dist']:.0f}"

        # Early warning at 80-120m (was 100-150m)
        if 80 < distance_to_zone < 120 and zone_id not in self.warned_braking_zones:
            if self.current_speed > next_zone['min_speed'] + 60:
                self.speak(say('brake_warning'), priority=SmartTTSQueue.PRIORITY_HIGH, valid_range=80)
                self.warned_braking_zones.add(zone_id)
                self._set_cooldown('brake')
                return

        # Brake NOW - only when really close
        if 0 < distance_to_zone < warning_dist:
            if self.current_throttle > 0.3 and self.current_brake < 0.2:
                if next_zone['min_gear'] < self.current_gear - 1:
                    self.speak(say('brake_with_gear', gear=next_zone['min_gear']),
                              priority=SmartTTSQueue.PRIORITY_CRITICAL, valid_range=60)
                else:
                    self.speak(say('brake_now'),
                              priority=SmartTTSQueue.PRIORITY_CRITICAL, valid_range=60)
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

    def _check_delta(self):
        if not self._check_cooldown('delta'):
            return
        if abs(self.current_delta) > 0.3:
            delta_speech = self._format_delta_speech(self.current_delta)
            if self.current_delta > 0:
                self.speak(say('delta_plus', delta=delta_speech), priority=SmartTTSQueue.PRIORITY_LOW)
            else:
                self.speak(say('delta_minus', delta=delta_speech), priority=SmartTTSQueue.PRIORITY_LOW)
            self._set_cooldown('delta')

    # =========================================================================
    # TELEMETRY UPDATE
    # =========================================================================
    def update_telemetry(self, speed, throttle, brake, gear, lap_distance,
                         lap_num, current_lap_time, last_lap_time,
                         lap_invalid=0, total_warnings=0, corner_warnings=0, penalties=0):
        """Process incoming telemetry with validity tracking."""
        
        # New lap detection
        if lap_num != self.current_lap_num:
            if self.current_lap_num > 0 and last_lap_time > 0:
                self._finish_lap(self.current_lap_num, last_lap_time)

            self.current_lap_num = lap_num
            self.current_lap_data = []
            self.warned_braking_zones.clear()
            self.lap_is_invalid = False
            self.lap_was_invalid = False
            
            for cd in self.cooldowns.values():
                cd['last_dist'] = -1000
            self.tts_queue.clear()

            if lap_num == 0:
                self.speak(say('formation_lap'), force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
            elif lap_num >= 1:
                if self.reference is None:
                    self.speak(say('lap_start_no_ref', lap=lap_num), force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
                else:
                    target = self._format_time_speech(self.reference_lap_time)
                    self.speak(say('lap_start_with_ref', lap=lap_num, target=target), force=True, priority=SmartTTSQueue.PRIORITY_HIGH)

        # Store last speed for crash detection
        self.last_speed = self.current_speed

        # Update state
        self.last_lap_distance = self.current_lap_distance
        self.current_lap_distance = lap_distance
        self.current_speed = speed
        self.current_gear = gear
        self.current_throttle = throttle
        self.current_brake = brake
        self.current_lap_time = current_lap_time

        # Check lap validity
        self._check_lap_validity(lap_invalid == 1)

        # Check penalties/warnings
        self._check_penalties(total_warnings, corner_warnings, penalties)

        # Check for crash
        self._check_crash()

        # Record sample
        if lap_num > 0:
            self.current_lap_data.append({
                'lap_distance': lap_distance,
                'current_lap_time': current_lap_time,
                'speed': speed,
                'throttle': throttle,
                'brake': brake,
                'gear': gear,
            })

        # Coaching
        self.analyze_and_coach()

        # Status print every 200m
        if int(self.current_lap_distance / 200) != int(self.last_lap_distance / 200):
            invalid_str = " [INVALID]" if self.lap_is_invalid else ""
            delta_str = f" | Δ: {self.current_delta:+.2f}s" if self.track_analyzer else ""
            label = "Out" if lap_num == 0 else f"L{lap_num}"
            print(f"  {label} | {self.current_lap_distance:4.0f}m | "
                  f"{self.current_speed:3.0f} km/h | G{self.current_gear}{delta_str}{invalid_str}")

    def update_damage(self, fl_wing, fr_wing, rear_wing, floor, sidepod):
        """Process damage packet data."""
        self._check_damage(fl_wing, fr_wing, rear_wing, floor, sidepod)
        self.front_left_wing_damage = fl_wing
        self.front_right_wing_damage = fr_wing
        self.rear_wing_damage = rear_wing
        self.floor_damage = floor
        self.sidepod_damage = sidepod

    def shutdown(self):
        self.tts_running = False
        self.tts_thread.join(timeout=2)


# =============================================================================
# MAIN
# =============================================================================
def main():
    coach = F1Coach()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    sock.settimeout(1.0)

    print(f"\n  Listening on {UDP_IP}:{UDP_PORT}")
    print("  Waiting for F1 25 telemetry...\n")

    packet_count = 0
    last_lap_distance = None
    crossed_start_finish = False
    lap_data = {}

    try:
        while True:
            try:
                data, addr = sock.recvfrom(4096)
                packet_count += 1

                if len(data) >= HEADER_SIZE:
                    header = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
                    packet_id = header[5]
                    player_car_index = header[10]

                    # Lap Data Packet (ID 2)
                    if packet_id == 2:
                        offset = HEADER_SIZE + (player_car_index * LAP_DATA_SIZE)
                        if len(data) >= offset + LAP_DATA_SIZE:
                            lap = struct.unpack(LAP_DATA_FMT, data[offset:offset + LAP_DATA_SIZE])
                            
                            lap_distance = lap[10]      # lapDistance
                            raw_lap_num = int(lap[14])  # currentLapNum
                            lap_invalid = lap[18]       # currentLapInvalid
                            penalties = lap[19]         # penalties
                            total_warnings = lap[20]    # totalWarnings
                            corner_warnings = lap[21]   # cornerCuttingWarnings

                            # Handle formation lap
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
                                'lap_invalid': lap_invalid,
                                'total_warnings': total_warnings,
                                'corner_warnings': corner_warnings,
                                'penalties': penalties,
                            }

                    # Event Packet (ID 3)
                    elif packet_id == 3:
                        if len(data) >= HEADER_SIZE + 4:
                            event_code = data[HEADER_SIZE:HEADER_SIZE + 4]
                            event_data = data[HEADER_SIZE + 4:] if len(data) > HEADER_SIZE + 4 else b''
                            coach.handle_event(event_code, event_data)

                    # Car Telemetry Packet (ID 6)
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
                                    lap_distance=lap_data['lap_distance'],
                                    lap_num=lap_data['current_lap_num'],
                                    current_lap_time=lap_data['current_lap_time'],
                                    last_lap_time=lap_data['last_lap_time'],
                                    lap_invalid=lap_data.get('lap_invalid', 0),
                                    total_warnings=lap_data.get('total_warnings', 0),
                                    corner_warnings=lap_data.get('corner_warnings', 0),
                                    penalties=lap_data.get('penalties', 0),
                                )

                    # Car Damage Packet (ID 10)
                    elif packet_id == 10:
                        # Calculate offset for player's car damage data
                        # Each car's damage data is 42 bytes in F1 25
                        damage_per_car = 42
                        offset = HEADER_SIZE + (player_car_index * damage_per_car)
                        
                        if len(data) >= offset + 20:  # We only need first 20 bytes for wing/floor
                            # Skip tyre wear (16 bytes) and tyre damage (4 bytes)
                            damage_offset = offset + 20
                            if len(data) >= damage_offset + 6:
                                damage_data = struct.unpack('<BBBBBB', data[damage_offset:damage_offset + 6])
                                # frontLeftWing, frontRightWing, rearWing, floor, diffuser, sidepod
                                coach.update_damage(
                                    fl_wing=damage_data[0],
                                    fr_wing=damage_data[1],
                                    rear_wing=damage_data[2],
                                    floor=damage_data[3],
                                    sidepod=damage_data[5],
                                )

            except socket.timeout:
                pass

    except KeyboardInterrupt:
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


if __name__ == "__main__":
    main()