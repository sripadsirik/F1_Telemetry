import socket
import struct
import pandas as pd
import pyttsx3
import time
import threading
import queue
import random
import numpy as np

# F1 25 UDP Settings
UDP_IP = "0.0.0.0"
UDP_PORT = 20777

# Packet formats
HEADER_FMT = '<HBBBBBQfIIBB'
HEADER_SIZE = struct.calcsize(HEADER_FMT)
CAR_TELEM_FMT = '<HfffBbHBBHHHHHBBBBBBBBHffffBBBB'
CAR_TELEM_SIZE = struct.calcsize(CAR_TELEM_FMT)
LAP_DATA_FMT = '<IIHBHBHBHBfffBBBBBBBBBBBBBBHHBfB'
LAP_DATA_SIZE = struct.calcsize(LAP_DATA_FMT)

COACH_NAME = "Marco"


# =============================================================================
# DIALOGUE BANK - Multiple variations for each situation
# =============================================================================
DIALOGUES = {
    'intro': [
        f"Hey, it's {COACH_NAME}. I'm your race engineer today. Get out there, put in a clean lap, and I'll start coaching you from there. Let's go.",
    ],
    'formation_lap': [
        "Connected. I can see the telemetry. Formation lap, take it easy.",
        "Telemetry online. Outlap, so just warming up the tires.",
        "Got you on screen. Formation lap, no need to push yet.",
    ],
    'lap_start_no_ref': [
        "Lap {lap}. Push hard, this one sets the reference.",
        "Lap {lap}. Give me a clean one, I need baseline data.",
        "Lap {lap} begins. Show me what you've got.",
    ],
    'lap_start_with_ref': [
        "Lap {lap}. Let's go.",
        "Lap {lap}. Time to beat: {target}",
        "Lap {lap}. Stay focused.",
        "New lap. Reference is {target}, let's see if you can match it.",
    ],
    'baseline_set': [
        "Nice one. {time}. That's our baseline. Now let's see if you can beat it.",
        "Good lap. {time}. I've got the data, now let's improve on it.",
        "{time}. Solid baseline. I'll guide you from here.",
    ],
    'purple_lap': [
        "Purple lap! {time}. That's {delta} faster. New reference set. Keep pushing.",
        "Fastest lap! {time}. You found {delta}. That's the new benchmark.",
        "Beautiful! {time}, {delta} quicker. I'm updating the reference.",
    ],
    'lap_close': [
        "{time}. So close, just {delta} off. You've got the pace.",
        "{time}. Within {delta}, that's right there. Keep at it.",
        "That's a {time}. Only {delta} down. The pace is in you.",
    ],
    'lap_ok': [
        "{time}. Plus {delta}. Not bad, but there's time on the table.",
        "{time}. We lost {delta} there. Small margins to find.",
        "{time}. {delta} off the pace. Let's tighten up the next one.",
    ],
    'lap_slow': [
        "{time}. We lost {delta} seconds there. Let's tighten it up.",
        "{time}. That's {delta} down. Reset and go again.",
        "{time}. {delta} off. Forget that one, focus on the next lap.",
    ],
    
    # PREDICTIVE BRAKING CALLS
    'brake_warning_early': [
        "Braking zone ahead",
        "Big stop coming up",
        "Prepare to brake",
        "Heavy braking soon",
    ],
    'brake_now': [
        "Brake now",
        "Brake, brake",
        "Hit the brakes",
        "Brake hard",
    ],
    'brake_with_gear': [
        "Brake, down to {gear}",
        "Brake now, {gear}th gear",
        "Braking zone, drop to {gear}",
    ],
    
    # GEAR COACHING
    'downshift': [
        "Down to {gear}",
        "Drop it to {gear}",
        "{gear}th gear",
        "Downshift, {gear}",
    ],
    'upshift': [
        "Up to {gear}",
        "{gear}th gear now",
    ],
    
    # THROTTLE COACHING
    'get_on_power': [
        "Get on the power",
        "Throttle now",
        "Power down",
        "On the gas",
        "Full throttle",
    ],
    'lift': [
        "Lift",
        "Easy on throttle",
        "Back off slightly",
    ],
    
    # SPEED COACHING
    'carry_more_speed': [
        "You can carry more speed here",
        "More speed through here",
        "Don't be shy, carry the speed",
        "Trust the car, more speed",
    ],
    'good_speed': [
        "Good speed",
        "Nice pace",
        "That's the speed",
        "Nailed it",
    ],
    'too_fast_entry': [
        "Too hot into that one",
        "Bit too fast on entry",
        "Scrubbed some speed there",
    ],
    
    # DELTA CALLOUTS
    'delta_plus': [
        "Plus {delta}",
        "Up {delta}",
        "{delta} down on reference",
    ],
    'delta_minus': [
        "Minus {delta}",
        "Down {delta}",
        "{delta} up on reference",
    ],
    
    # POSITIVE REINFORCEMENT
    'good_corner': [
        "Nice corner",
        "Good turn",
        "Clean",
        "Tidy",
    ],
    'good_braking': [
        "Good braking",
        "Nice stop",
        "Perfect braking point",
    ],
    
    # SESSION END
    'session_end': [
        "Good session. See you next time.",
        "That's the session. Nice work out there.",
        "Session complete. Good job today.",
    ],
}

def say(category, **kwargs):
    """Get a random phrase from a category, formatted with kwargs."""
    phrases = DIALOGUES.get(category, [category])  # fallback to literal if not found
    phrase = random.choice(phrases)
    return phrase.format(**kwargs) if kwargs else phrase


# =============================================================================
# TRACK ANALYZER - Pre-processes reference lap to find braking zones, etc.
# =============================================================================
class TrackAnalyzer:
    """Analyzes a reference lap to identify key track features."""
    
    def __init__(self, reference_df):
        self.reference = reference_df.sort_values('lap_distance').reset_index(drop=True)
        self.braking_zones = []
        self.acceleration_zones = []
        self.corners = []
        self.track_length = self.reference['lap_distance'].max()
        
        self._analyze()
    
    def _analyze(self):
        """Identify all track features from reference lap."""
        df = self.reference
        
        # Smooth the data slightly to avoid noise
        df['brake_smooth'] = df['brake'].rolling(window=5, min_periods=1).mean()
        df['throttle_smooth'] = df['throttle'].rolling(window=5, min_periods=1).mean()
        df['speed_smooth'] = df['speed'].rolling(window=5, min_periods=1).mean()
        
        # Find braking zones (where brake > 0.2)
        in_braking = False
        zone_start = None
        
        for idx, row in df.iterrows():
            if row['brake_smooth'] > 0.2 and not in_braking:
                # Start of braking zone
                in_braking = True
                zone_start = idx
            elif row['brake_smooth'] < 0.1 and in_braking:
                # End of braking zone
                in_braking = False
                if zone_start is not None:
                    zone_data = df.iloc[zone_start:idx]
                    if len(zone_data) > 3:  # Ignore tiny blips
                        self.braking_zones.append({
                            'start_dist': zone_data['lap_distance'].iloc[0],
                            'end_dist': zone_data['lap_distance'].iloc[-1],
                            'entry_speed': zone_data['speed'].iloc[0],
                            'min_speed': zone_data['speed'].min(),
                            'min_gear': int(zone_data['gear'].min()),
                            'brake_start_idx': zone_start,
                        })
        
        # Find acceleration zones (where throttle > 0.8 after low speed)
        for idx, row in df.iterrows():
            if row['throttle_smooth'] > 0.8 and row['speed_smooth'] < 150:
                # Check if this is start of acceleration
                if idx > 5:
                    prev_throttle = df.iloc[idx-5:idx]['throttle_smooth'].mean()
                    if prev_throttle < 0.5:
                        self.acceleration_zones.append({
                            'dist': row['lap_distance'],
                            'speed': row['speed'],
                            'gear': int(row['gear']),
                        })
        
        print(f"\n  Track Analysis Complete:")
        print(f"  - Track length: {self.track_length:.0f}m")
        print(f"  - Braking zones found: {len(self.braking_zones)}")
        print(f"  - Acceleration zones found: {len(self.acceleration_zones)}")
        
        # Print braking zone summary
        for i, zone in enumerate(self.braking_zones):
            print(f"    Zone {i+1}: {zone['start_dist']:.0f}m, "
                  f"{zone['entry_speed']:.0f}->{zone['min_speed']:.0f} km/h, "
                  f"gear {zone['min_gear']}")
    
    def get_next_braking_zone(self, current_distance):
        """Get the next braking zone ahead of current position."""
        for zone in self.braking_zones:
            if zone['start_dist'] > current_distance:
                return zone
        # Wrap around to first zone if near end of lap
        if self.braking_zones:
            return self.braking_zones[0]
        return None
    
    def get_reference_at_distance(self, lap_distance):
        """Get reference data at a specific distance."""
        idx = (self.reference['lap_distance'] - lap_distance).abs().idxmin()
        return self.reference.iloc[idx]
    
    def calculate_braking_warning_distance(self, current_speed, zone):
        """Calculate how far ahead to warn about braking based on current speed."""
        if zone is None:
            return 0
        
        speed_diff = current_speed - zone['min_speed']
        if speed_diff <= 0:
            return 0
        
        # Rough physics: higher speed = need more warning
        # Assume ~1.5g braking, reaction time ~0.3s
        # warning_dist = reaction_distance + safety_margin
        reaction_time = 0.4  # seconds
        safety_margin = 30   # meters
        
        # Distance to react at current speed (m/s * time)
        reaction_dist = (current_speed / 3.6) * reaction_time
        
        # More warning for bigger speed drops
        speed_factor = speed_diff / 100  # normalized
        extra_margin = speed_factor * 50  # up to 50m extra for big stops
        
        return reaction_dist + safety_margin + extra_margin


# =============================================================================
# SMART TTS QUEUE - Prioritizes messages and drops stale ones
# =============================================================================
class SmartTTSQueue:
    """Priority-based TTS queue that drops stale messages."""
    
    PRIORITY_CRITICAL = 0   # Brake warnings
    PRIORITY_HIGH = 1       # Gear changes, lap times
    PRIORITY_MEDIUM = 2     # Speed coaching
    PRIORITY_LOW = 3        # Delta callouts, positive feedback
    
    def __init__(self):
        self.queue = queue.PriorityQueue()
        self.last_message_time = 0
        self.current_distance = 0
        self.message_counter = 0  # For stable sorting
        
    def put(self, message, priority=PRIORITY_MEDIUM, valid_distance_range=200):
        """Add a message with priority. Messages expire after valid_distance_range meters."""
        self.message_counter += 1
        item = (
            priority,
            self.message_counter,  # Ensures FIFO within same priority
            {
                'message': message,
                'distance': self.current_distance,
                'valid_range': valid_distance_range,
                'timestamp': time.time(),
            }
        )
        
        # Limit queue size - drop lowest priority if too full
        if self.queue.qsize() >= 3:
            # Just don't add low priority messages when queue is full
            if priority >= self.PRIORITY_MEDIUM:
                return False
        
        self.queue.put(item)
        return True
    
    def get(self, current_distance, timeout=0.1):
        """Get next valid message, skipping stale ones."""
        self.current_distance = current_distance
        
        while True:
            try:
                priority, counter, data = self.queue.get(timeout=timeout)
            except queue.Empty:
                return None
            
            # Check if message is still valid (not too far from where it was queued)
            distance_traveled = abs(current_distance - data['distance'])
            age = time.time() - data['timestamp']
            
            # Skip stale messages
            if distance_traveled > data['valid_range'] or age > 3.0:
                continue  # Drop this message, try next
            
            return data['message']
    
    def update_distance(self, distance):
        """Update current track position."""
        self.current_distance = distance
    
    def clear(self):
        """Clear all pending messages."""
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break


# =============================================================================
# F1 COACH - Main coaching logic
# =============================================================================
class F1Coach:
    def __init__(self):
        print("=" * 70)
        print(f"  {COACH_NAME.upper()} - YOUR F1 RACE ENGINEER (v2.0 - Predictive)")
        print("=" * 70)

        # Coach state
        self.current_lap_distance = 0
        self.last_lap_distance = 0
        self.current_speed = 0
        self.current_gear = 0
        self.current_throttle = 0
        self.current_brake = 0
        self.current_lap_num = -1
        self.current_lap_time = 0
        self.current_delta = 0

        # Lap tracking
        self.current_lap_data = []
        self.completed_laps = {}
        self.reference = None
        self.reference_lap_num = None
        self.reference_lap_time = None
        self.track_analyzer = None

        # Cooldown tracking - per category
        self.cooldowns = {
            'brake': {'last_dist': -1000, 'cooldown': 150},
            'gear': {'last_dist': -1000, 'cooldown': 100},
            'throttle': {'last_dist': -1000, 'cooldown': 150},
            'speed': {'last_dist': -1000, 'cooldown': 200},
            'delta': {'last_dist': -1000, 'cooldown': 400},
            'positive': {'last_dist': -1000, 'cooldown': 300},
        }
        self.last_cue_time = 0
        self.time_cooldown = 1.0

        # Braking zone tracking
        self.warned_braking_zones = set()  # Track which zones we've warned about this lap
        self.current_braking_zone = None

        # Smart TTS
        self.tts_queue = SmartTTSQueue()
        self.tts_running = True
        self.tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
        self.tts_thread.start()

        # Intro
        self.speak(say('intro'), force=True, priority=SmartTTSQueue.PRIORITY_HIGH)

        print(f"\n  {COACH_NAME}: Ready when you are. Complete a lap to set the baseline.\n")

    def _tts_worker(self):
        """TTS worker thread with smart queue."""
        while self.tts_running:
            try:
                message = self.tts_queue.get(self.current_lap_distance, timeout=0.1)
                if message is None:
                    continue

                engine = None
                try:
                    engine = pyttsx3.init()
                    engine.setProperty('rate', 175)  # Slightly faster for urgency
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
        """Queue a message for TTS."""
        current_time = time.time()
        if not force and current_time - self.last_cue_time < self.time_cooldown:
            return False

        if self.tts_queue.put(message, priority, valid_range):
            self.last_cue_time = current_time
            print(f"  {COACH_NAME}: {message}")
            return True
        return False

    def _check_cooldown(self, category):
        """Check if a category is off cooldown."""
        cd = self.cooldowns.get(category)
        if cd is None:
            return True
        return abs(self.current_lap_distance - cd['last_dist']) >= cd['cooldown']

    def _set_cooldown(self, category):
        """Set cooldown for a category."""
        if category in self.cooldowns:
            self.cooldowns[category]['last_dist'] = self.current_lap_distance

    def _format_time_speech(self, time_seconds):
        """Format time for speech with exact decimals."""
        mins = int(time_seconds // 60)
        secs = time_seconds % 60
        whole_secs = int(secs)
        milliseconds = int(round((secs - whole_secs) * 1000))
        
        if mins > 0:
            return f"{mins} minute {whole_secs} point {milliseconds:03d}"
        else:
            return f"{whole_secs} point {milliseconds:03d}"

    def _format_delta_speech(self, delta):
        """Format delta for speech."""
        abs_delta = abs(delta)
        whole = int(abs_delta)
        milliseconds = int(round((abs_delta - whole) * 1000))
        
        if whole > 0:
            return f"{whole} point {milliseconds:03d}"
        else:
            return f"0 point {milliseconds:03d}"

    def _finish_lap(self, lap_num, lap_time):
        """Handle lap completion."""
        if not self.current_lap_data or lap_time <= 0:
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
            
            # Analyze the track
            self.track_analyzer = TrackAnalyzer(self.reference)
            
            print(f"\n{'='*70}")
            print(f"  NEW FASTEST LAP! Lap {lap_num} - {mins}:{secs:06.3f}")
            print(f"  Using as reference ({len(lap_df)} data points)")
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
            
            print(f"\n{'='*70}")
            print(f"  LAP {lap_num} COMPLETE - {mins}:{secs:06.3f} (+{delta:.3f}s)")
            print(f"  Reference: Lap {self.reference_lap_num} - {self.reference_lap_time:.3f}s")
            print(f"{'='*70}\n")

            if delta < 0.5:
                self.speak(say('lap_close', time=time_speech, delta=delta_speech),
                          force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
            elif delta < 2.0:
                self.speak(say('lap_ok', time=time_speech, delta=delta_speech),
                          force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
            else:
                self.speak(say('lap_slow', time=time_speech, delta=delta_speech),
                          force=True, priority=SmartTTSQueue.PRIORITY_HIGH)

    def calculate_delta(self):
        """Calculate time delta vs reference."""
        if self.track_analyzer is None or self.current_lap_distance < 100:
            return 0
        ref = self.track_analyzer.get_reference_at_distance(self.current_lap_distance)
        return self.current_lap_time - ref['current_lap_time']

    def analyze_and_coach(self):
        """Main coaching logic - predictive and reactive."""
        if self.track_analyzer is None:
            return
        if self.current_lap_distance < 50:
            return

        self.current_delta = self.calculate_delta()
        self.tts_queue.update_distance(self.current_lap_distance)

        # === PREDICTIVE BRAKING ===
        self._check_braking_zones()

        # === GEAR COACHING ===
        self._check_gear()

        # === THROTTLE COACHING ===
        self._check_throttle()

        # === SPEED COACHING ===
        self._check_speed()

        # === DELTA CALLOUTS ===
        self._check_delta()

    def _check_braking_zones(self):
        """Predictive braking zone warnings."""
        if not self._check_cooldown('brake'):
            return

        next_zone = self.track_analyzer.get_next_braking_zone(self.current_lap_distance)
        if next_zone is None:
            return

        distance_to_zone = next_zone['start_dist'] - self.current_lap_distance
        
        # Handle lap wraparound
        if distance_to_zone < 0:
            distance_to_zone += self.track_analyzer.track_length

        # Calculate when to warn
        warning_dist = self.track_analyzer.calculate_braking_warning_distance(
            self.current_speed, next_zone
        )

        zone_id = f"{next_zone['start_dist']:.0f}"

        # Early warning (100-150m before braking point)
        if 100 < distance_to_zone < 150 and zone_id not in self.warned_braking_zones:
            if self.current_speed > next_zone['min_speed'] + 50:
                self.speak(say('brake_warning_early'),
                          priority=SmartTTSQueue.PRIORITY_HIGH, valid_range=100)
                self.warned_braking_zones.add(zone_id)
                self._set_cooldown('brake')
                return

        # Brake NOW call (when within warning distance and still on throttle)
        if 0 < distance_to_zone < warning_dist:
            if self.current_throttle > 0.3 and self.current_brake < 0.2:
                if next_zone['min_gear'] < self.current_gear - 1:
                    self.speak(say('brake_with_gear', gear=next_zone['min_gear']),
                              priority=SmartTTSQueue.PRIORITY_CRITICAL, valid_range=80)
                else:
                    self.speak(say('brake_now'),
                              priority=SmartTTSQueue.PRIORITY_CRITICAL, valid_range=80)
                self._set_cooldown('brake')

    def _check_gear(self):
        """Gear coaching based on reference."""
        if not self._check_cooldown('gear'):
            return

        ref = self.track_analyzer.get_reference_at_distance(self.current_lap_distance)
        ref_gear = int(ref['gear'])

        # Suggest downshift if 2+ gears too high
        if self.current_gear > ref_gear + 1:
            self.speak(say('downshift', gear=ref_gear),
                      priority=SmartTTSQueue.PRIORITY_HIGH, valid_range=100)
            self._set_cooldown('gear')

    def _check_throttle(self):
        """Throttle application coaching."""
        if not self._check_cooldown('throttle'):
            return

        ref = self.track_analyzer.get_reference_at_distance(self.current_lap_distance)

        # Should be on power but isn't
        if ref['throttle'] > 0.8 and self.current_throttle < 0.3 and self.current_brake < 0.1:
            self.speak(say('get_on_power'),
                      priority=SmartTTSQueue.PRIORITY_MEDIUM, valid_range=100)
            self._set_cooldown('throttle')

    def _check_speed(self):
        """Speed coaching - carrying speed through corners."""
        if not self._check_cooldown('speed'):
            return

        ref = self.track_analyzer.get_reference_at_distance(self.current_lap_distance)
        speed_diff = self.current_speed - ref['speed']

        # Too slow through a corner
        if speed_diff < -15 and self.current_speed < 200 and ref['speed'] < 250:
            self.speak(say('carry_more_speed'),
                      priority=SmartTTSQueue.PRIORITY_LOW, valid_range=150)
            self._set_cooldown('speed')
            return

        # Good speed - positive feedback
        if speed_diff > 10 and ref['speed'] < 200 and self.current_speed < 250:
            if self._check_cooldown('positive'):
                self.speak(say('good_speed'),
                          priority=SmartTTSQueue.PRIORITY_LOW, valid_range=100)
                self._set_cooldown('positive')

    def _check_delta(self):
        """Periodic delta callouts."""
        if not self._check_cooldown('delta'):
            return

        if abs(self.current_delta) > 0.3:
            delta_speech = self._format_delta_speech(self.current_delta)
            if self.current_delta > 0:
                self.speak(say('delta_plus', delta=delta_speech),
                          priority=SmartTTSQueue.PRIORITY_LOW, valid_range=200)
            else:
                self.speak(say('delta_minus', delta=delta_speech),
                          priority=SmartTTSQueue.PRIORITY_LOW, valid_range=200)
            self._set_cooldown('delta')

    def update_telemetry(self, speed, throttle, brake, gear, lap_distance,
                         lap_num, current_lap_time, last_lap_time):
        """Process incoming telemetry."""
        # Detect new lap
        if lap_num != self.current_lap_num:
            # Finish previous lap
            if self.current_lap_num > 0 and last_lap_time > 0:
                self._finish_lap(self.current_lap_num, last_lap_time)

            self.current_lap_num = lap_num
            self.current_lap_data = []
            self.warned_braking_zones.clear()  # Reset warnings for new lap
            
            # Reset cooldowns for new lap
            for cd in self.cooldowns.values():
                cd['last_dist'] = -1000

            # Clear any stale messages
            self.tts_queue.clear()

            if lap_num == 0:
                self.speak(say('formation_lap'), force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
            elif lap_num >= 1:
                if self.reference is None:
                    self.speak(say('lap_start_no_ref', lap=lap_num),
                              force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
                else:
                    target = self._format_time_speech(self.reference_lap_time)
                    self.speak(say('lap_start_with_ref', lap=lap_num, target=target),
                              force=True, priority=SmartTTSQueue.PRIORITY_HIGH)

        # Update state
        self.last_lap_distance = self.current_lap_distance
        self.current_lap_distance = lap_distance
        self.current_speed = speed
        self.current_gear = gear
        self.current_throttle = throttle
        self.current_brake = brake
        self.current_lap_time = current_lap_time

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

        # Print status every 200m
        if int(self.current_lap_distance / 200) != int(self.last_lap_distance / 200):
            delta_str = ""
            if self.track_analyzer is not None and self.current_delta != 0:
                delta_str = f" | Delta: {self.current_delta:+.2f}s"
            label = "Formation" if lap_num == 0 else f"Lap {lap_num}"
            print(f"  {label} | Dist: {self.current_lap_distance:4.0f}m | "
                  f"Speed: {self.current_speed:3.0f} km/h | "
                  f"Gear: {self.current_gear}{delta_str}")

    def shutdown(self):
        """Clean shutdown."""
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

                    if packet_id == 2:
                        offset = HEADER_SIZE + (player_car_index * LAP_DATA_SIZE)
                        if len(data) >= offset + LAP_DATA_SIZE:
                            lap = struct.unpack(LAP_DATA_FMT, data[offset:offset + LAP_DATA_SIZE])
                            lap_distance = lap[10]
                            raw_lap_num = int(lap[14])

                            if last_lap_distance is not None and last_lap_distance < 0 and lap_distance >= 0:
                                if not crossed_start_finish:
                                    crossed_start_finish = True
                                    print(f"\n  >>> CROSSED START/FINISH - LAP 1 BEGINS <<<\n")

                            if not crossed_start_finish:
                                current_lap_num = 0
                            else:
                                current_lap_num = raw_lap_num

                            last_lap_distance = lap_distance

                            lap_data = {
                                'lap_distance': lap_distance,
                                'current_lap_num': current_lap_num,
                                'current_lap_time': lap[1] / 1000.0,
                                'last_lap_time': lap[0] / 1000.0,
                            }

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
                                )
            except socket.timeout:
                pass

    except KeyboardInterrupt:
        print(f"\n\n{'='*70}")
        print(f"  {COACH_NAME}: {say('session_end')}")
        print(f"{'='*70}")
        print(f"  Total packets: {packet_count:,}")
        if coach.completed_laps:
            print(f"  Laps completed: {len(coach.completed_laps)}")
            print(f"  Fastest: Lap {coach.reference_lap_num} - {coach.reference_lap_time:.3f}s")
        coach.speak(say('session_end'), force=True, priority=SmartTTSQueue.PRIORITY_HIGH)
        time.sleep(3)
        coach.shutdown()
        sock.close()


if __name__ == "__main__":
    main()