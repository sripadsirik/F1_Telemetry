import socket
import struct
import pandas as pd
import pyttsx3
import time
import threading
import queue

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


class F1Coach:
    def __init__(self):
        print("=" * 70)
        print(f"  {COACH_NAME.upper()} - YOUR F1 RACE ENGINEER")
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

        # Lap tracking for dynamic reference
        self.current_lap_data = []
        self.completed_laps = {}
        self.reference = None
        self.reference_lap_num = None
        self.reference_lap_time = None

        # Cooldown tracking
        self.last_cue_distance = -1000
        self.cue_cooldown = 80
        self.last_cue_time = 0
        self.time_cooldown = 1.5

        # Delta callout tracking
        self.last_delta_distance = -1000
        self.delta_callout_interval = 500  # call out delta every 500m

        # Threading for TTS - use Queue instead of list for thread safety
        self.tts_queue = queue.Queue()
        self.tts_running = True
        self.tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
        self.tts_thread.start()

        # Intro
        self.speak(f"Hey, it's {COACH_NAME}. I'm your race engineer today. "
                   "Get out there, put in a clean lap, and I'll start coaching you from there. Let's go.")

        print(f"\n  {COACH_NAME}: Ready when you are. Complete a lap to set the baseline.\n")

    def _tts_worker(self):
        """TTS worker thread - creates fresh engine for each message."""
        while self.tts_running:
            try:
                # Wait for a message with timeout so we can check tts_running
                try:
                    message = self.tts_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                # Create a completely fresh engine for each message
                engine = None
                try:
                    engine = pyttsx3.init()
                    engine.setProperty('rate', 170)
                    engine.setProperty('volume', 1.0)
                    engine.say(message)
                    engine.runAndWait()
                except Exception as e:
                    print(f"  [TTS Error: {e}]")
                finally:
                    # Ensure engine is properly cleaned up
                    if engine:
                        try:
                            engine.stop()
                            del engine
                        except:
                            pass

                self.tts_queue.task_done()

            except Exception as e:
                print(f"  [TTS Worker Error: {e}]")

    def speak(self, message, force=False):
        current_time = time.time()
        if not force and current_time - self.last_cue_time < self.time_cooldown:
            return

        # Don't queue up too many messages
        if self.tts_queue.qsize() < 3:
            self.tts_queue.put(message)

        self.last_cue_time = current_time
        print(f"  {COACH_NAME}: {message}")

    def _format_time_speech(self, time_seconds):
        """Format time for speech with exact decimals."""
        mins = int(time_seconds // 60)
        secs = time_seconds % 60
        # Split seconds into whole and decimal parts
        whole_secs = int(secs)
        decimal_part = secs - whole_secs
        # Get 3 decimal places
        milliseconds = int(round(decimal_part * 1000))
        
        if mins > 0:
            return f"{mins} minute {whole_secs} point {milliseconds:03d}"
        else:
            return f"{whole_secs} point {milliseconds:03d}"

    def _format_delta_speech(self, delta):
        """Format delta time for speech with exact decimals."""
        abs_delta = abs(delta)
        whole = int(abs_delta)
        decimal_part = abs_delta - whole
        milliseconds = int(round(decimal_part * 1000))
        
        if whole > 0:
            return f"{whole} point {milliseconds:03d}"
        else:
            return f"0 point {milliseconds:03d}"

    def _finish_lap(self, lap_num, lap_time):
        if not self.current_lap_data or lap_time <= 0:
            return

        lap_df = pd.DataFrame(self.current_lap_data)
        self.completed_laps[lap_num] = {'time': lap_time, 'data': lap_df}

        mins = int(lap_time // 60)
        secs = lap_time % 60
        time_speech = self._format_time_speech(lap_time)

        if self.reference is None or lap_time < self.reference_lap_time:
            old_ref = self.reference_lap_time
            self.reference = lap_df
            self.reference_lap_num = lap_num
            self.reference_lap_time = lap_time
            print(f"\n{'='*70}")
            print(f"  NEW FASTEST LAP! Lap {lap_num} - {mins}:{secs:06.3f}")
            print(f"  Using as reference ({len(lap_df)} data points)")
            print(f"{'='*70}\n")

            if old_ref is None:
                self.speak(f"Nice one. {time_speech}. That's our baseline. "
                           "Now let's see if you can beat it.", force=True)
            else:
                improvement = old_ref - lap_time
                improvement_speech = self._format_delta_speech(improvement)
                self.speak(f"Purple lap! {time_speech}. "
                           f"That's {improvement_speech} seconds faster. New reference set. Keep pushing.", force=True)
        else:
            delta = lap_time - self.reference_lap_time
            delta_speech = self._format_delta_speech(delta)
            print(f"\n{'='*70}")
            print(f"  LAP {lap_num} COMPLETE - {mins}:{secs:06.3f} (+{delta:.3f}s)")
            print(f"  Reference: Lap {self.reference_lap_num} - {self.reference_lap_time:.3f}s")
            print(f"{'='*70}\n")

            if delta < 0.5:
                self.speak(f"{time_speech}. So close, just {delta_speech} off. You've got the pace.", force=True)
            elif delta < 2.0:
                self.speak(f"{time_speech}. Plus {delta_speech}. Not bad, but there's time on the table.", force=True)
            else:
                self.speak(f"{time_speech}. We lost {delta_speech} seconds there. Let's tighten it up.", force=True)

    def get_reference_at_distance(self, lap_distance):
        idx = (self.reference['lap_distance'] - lap_distance).abs().idxmin()
        return self.reference.iloc[idx]

    def get_reference_ahead(self, lap_distance, lookahead=50):
        target_distance = lap_distance + lookahead
        idx = (self.reference['lap_distance'] - target_distance).abs().idxmin()
        return self.reference.iloc[idx]

    def calculate_delta(self):
        if self.reference is None or self.current_lap_distance < 100:
            return 0
        ref = self.get_reference_at_distance(self.current_lap_distance)
        ref_time = ref['current_lap_time']
        delta = self.current_lap_time - ref_time
        return delta

    def analyze_and_coach(self):
        if self.reference is None:
            return
        if self.current_lap_distance < 50:
            return

        self.current_delta = self.calculate_delta()

        # Delta callouts every 500m
        if abs(self.current_lap_distance - self.last_delta_distance) >= self.delta_callout_interval:
            self.last_delta_distance = self.current_lap_distance
            if abs(self.current_delta) > 0.3:
                delta_speech = self._format_delta_speech(self.current_delta)
                if self.current_delta > 0:
                    self.speak(f"Plus {delta_speech}")
                else:
                    self.speak(f"Minus {delta_speech}")

        # Coaching cues (distance-based cooldown)
        if abs(self.current_lap_distance - self.last_cue_distance) < self.cue_cooldown:
            return

        ref_current = self.get_reference_at_distance(self.current_lap_distance)
        ref_ahead = self.get_reference_ahead(self.current_lap_distance, lookahead=50)

        # Braking coaching
        if ref_ahead['brake'] > 0.3 and self.current_brake < 0.1:
            if self.current_throttle > 0.5:
                self.speak("Brake, brake, brake")
                self.last_cue_distance = self.current_lap_distance
                return

        # Gear coaching
        if self.current_gear > ref_current['gear'] + 1:
            target_gear = int(ref_current['gear'])
            self.speak(f"Drop it to {target_gear}")
            self.last_cue_distance = self.current_lap_distance
            return

        # Speed coaching
        speed_diff = self.current_speed - ref_current['speed']
        if speed_diff < -15 and self.current_speed < 200:
            self.speak("You can carry more speed through here")
            self.last_cue_distance = self.current_lap_distance
            return

        # Throttle coaching
        if ref_current['throttle'] > 0.8 and self.current_throttle < 0.3:
            if self.current_brake < 0.1:
                self.speak("Get on the power")
                self.last_cue_distance = self.current_lap_distance
                return

        # Positive feedback when matching or beating reference speed in corners
        if speed_diff > 10 and ref_current['speed'] < 200 and self.current_speed < 250:
            self.speak("Good speed, nice")
            self.last_cue_distance = self.current_lap_distance
            return

    def update_telemetry(self, speed, throttle, brake, gear, lap_distance,
                         lap_num, current_lap_time, last_lap_time):
        # Detect new lap
        if lap_num != self.current_lap_num:
            # Finish the previous lap if it was a real lap
            if self.current_lap_num > 0 and last_lap_time > 0:
                self._finish_lap(self.current_lap_num, last_lap_time)

            self.current_lap_num = lap_num
            self.current_lap_data = []
            self.last_cue_distance = -1000
            self.last_delta_distance = -1000

            if lap_num == 0:
                self.speak("Connected. I can see the telemetry. Formation lap, take it easy.", force=True)
            elif lap_num >= 1:
                if self.reference is None:
                    self.speak(f"Lap {lap_num}. Push hard, this one sets the reference.", force=True)
                else:
                    self.speak(f"Lap {lap_num}. Let's go.", force=True)

        # Update state
        self.last_lap_distance = self.current_lap_distance
        self.current_lap_distance = lap_distance
        self.current_speed = speed
        self.current_gear = gear
        self.current_throttle = throttle
        self.current_brake = brake
        self.current_lap_time = current_lap_time

        # Record sample for current lap
        if lap_num > 0:
            self.current_lap_data.append({
                'lap_distance': lap_distance,
                'current_lap_time': current_lap_time,
                'speed': speed,
                'throttle': throttle,
                'brake': brake,
                'gear': gear,
            })

        # Coaching (only if we have a reference)
        self.analyze_and_coach()

        # Print live status every 200m
        if int(self.current_lap_distance / 200) != int(self.last_lap_distance / 200):
            delta_str = ""
            if self.reference is not None and self.current_delta != 0:
                delta_str = f" | Delta: {self.current_delta:+.2f}s"
            label = "Formation" if lap_num == 0 else f"Lap {lap_num}"
            print(f"  {label} | Dist: {self.current_lap_distance:4.0f}m | "
                  f"Speed: {self.current_speed:3.0f} km/h | "
                  f"Gear: {self.current_gear}{delta_str}")

    def shutdown(self):
        """Clean shutdown of TTS thread."""
        self.tts_running = False
        self.tts_thread.join(timeout=2)


def main():
    coach = F1Coach()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    sock.settimeout(1.0)

    print(f"\n  Listening on {UDP_IP}:{UDP_PORT}")
    print("  Waiting for F1 25 telemetry...\n")

    packet_count = 0
    last_lap_distance = None
    crossed_start_finish = False  # Track if we've crossed the line
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

                    # Packet ID 2 = Lap Data
                    if packet_id == 2:
                        offset = HEADER_SIZE + (player_car_index * LAP_DATA_SIZE)
                        if len(data) >= offset + LAP_DATA_SIZE:
                            lap = struct.unpack(LAP_DATA_FMT, data[offset:offset + LAP_DATA_SIZE])
                            lap_distance = lap[10]
                            raw_lap_num = int(lap[14])

                            # Detect crossing the start/finish line
                            # This happens when lap_distance transitions from negative to positive
                            if last_lap_distance is not None and last_lap_distance < 0 and lap_distance >= 0:
                                if not crossed_start_finish:
                                    crossed_start_finish = True
                                    print(f"\n  >>> CROSSED START/FINISH - LAP 1 BEGINS <<<\n")

                            # Calculate display lap number:
                            # - Before crossing start/finish: Lap 0 (formation/outlap)
                            # - After crossing: Use raw_lap_num from telemetry
                            if not crossed_start_finish:
                                current_lap_num = 0
                            else:
                                current_lap_num = raw_lap_num

                            last_lap_distance = lap_distance

                            lap_data = {
                                'lap_distance': lap_distance,
                                'current_lap_num': current_lap_num,
                                'raw_current_lap_num': raw_lap_num,
                                'current_lap_time': lap[1] / 1000.0,
                                'last_lap_time': lap[0] / 1000.0,
                            }

                    # Packet ID 6 = Car Telemetry
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
        print(f"  {COACH_NAME}: Good session. See you next time.")
        print(f"{'='*70}")
        print(f"  Total packets: {packet_count:,}")
        if coach.completed_laps:
            print(f"  Laps completed: {len(coach.completed_laps)}")
            print(f"  Fastest: Lap {coach.reference_lap_num} - {coach.reference_lap_time:.3f}s")
        coach.speak("Good session. See you next time.", force=True)
        time.sleep(3)
        coach.shutdown()
        sock.close()


if __name__ == "__main__":
    main()