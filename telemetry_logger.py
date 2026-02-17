import socket
import struct
import csv
from datetime import datetime
import os


UDP_IP = "0.0.0.0"
UDP_PORT = 20777


sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
sock.settimeout(1.0)


HEADER_FMT = '<HBBBBBQfIIBB'
HEADER_SIZE = struct.calcsize(HEADER_FMT)

CAR_TELEM_FMT = '<HfffBbHBBHHHHHBBBBBBBBHffffBBBB'
CAR_TELEM_SIZE = struct.calcsize(CAR_TELEM_FMT)


MOTION_FMT = '<fffhhh' + 'hhh' + 'hhh' + 'hhh' + 'hhh'  
MOTION_SIZE = struct.calcsize(MOTION_FMT)

# Lap data packet format (Packet ID 2) - F1 25
LAP_DATA_FMT = '<IIHBHBHBHBfffBBBBBBBBBBBBBBHHBfB'
LAP_DATA_SIZE = struct.calcsize(LAP_DATA_FMT)


os.makedirs('logs', exist_ok=True)


timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
csv_file = f'logs/telemetry_{timestamp}.csv'
csv_writer = None
csv_handle = None

print(f"Logging telemetry to: {csv_file}")
print(f"Listening on {UDP_IP}:{UDP_PORT}")
print("Start driving in F1 25!")
print("-" * 60)

packet_count = 0
display_lap = 0
last_display_lap = None
last_raw_lap_num = None
last_lap_distance = None
crossed_start_finish = False  # Track if we've crossed the start/finish line
position_data = {}
lap_data = {}

try:
    while True:
        try:
            data, addr = sock.recvfrom(4096)
            packet_count += 1

            if len(data) >= HEADER_SIZE:
                header = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
                packet_id = header[5]
                session_time = header[7]
                frame_id = header[8]
                player_car_index = header[10]

                
                if packet_id == 0 and len(data) >= HEADER_SIZE + MOTION_SIZE:
                    offset = HEADER_SIZE + (player_car_index * 60)  
                    if len(data) >= offset + 24:
                        motion = struct.unpack('<ffffff', data[offset:offset+24])
                        position_data = {
                            'pos_x': motion[0],
                            'pos_y': motion[1],
                            'pos_z': motion[2],
                            'vel_x': motion[3],
                            'vel_y': motion[4],
                            'vel_z': motion[5]
                        }

                
                elif packet_id == 2:
                    offset = HEADER_SIZE + (player_car_index * LAP_DATA_SIZE)
                    if len(data) >= offset + LAP_DATA_SIZE:
                        lap = struct.unpack(LAP_DATA_FMT, data[offset:offset+LAP_DATA_SIZE])
                        lap_distance = lap[10]
                        raw_lap_num = int(lap[14])

                        # Detect crossing the start/finish line
                        # This happens when lap_distance transitions from negative to positive
                        if last_lap_distance is not None and last_lap_distance < 0 and lap_distance >= 0:
                            if not crossed_start_finish:
                                crossed_start_finish = True
                                print(f"\n>>> CROSSED START/FINISH - LAP 1 BEGINS <<<")
                        
                        # Calculate display lap number:
                        # - Before crossing start/finish: Lap 0 (formation/outlap)
                        # - After crossing: Use raw_lap_num from telemetry
                        if not crossed_start_finish:
                            current_lap_num = 0
                        else:
                            # Once we've crossed, trust the game's lap number
                            current_lap_num = raw_lap_num

                        # Emit lap-start events for subsequent laps (lap 2+)
                        if last_display_lap is not None and current_lap_num > last_display_lap and current_lap_num > 1:
                            last_time = lap[0] / 1000.0
                            completed_lap = current_lap_num - 1
                            time_str = f" (Lap {completed_lap}: {last_time:.3f}s)" if last_time > 0 else ""
                            print(f"\n>>> LAP {current_lap_num} STARTED <<<{time_str}")

                        display_lap = current_lap_num
                        last_display_lap = current_lap_num
                        last_raw_lap_num = raw_lap_num
                        last_lap_distance = lap_distance

                        lap_data = {
                            'last_lap_time': lap[0] / 1000.0,
                            'current_lap_time': lap[1] / 1000.0,
                            'sector1_time': lap[2] / 1000.0,
                            'sector2_time': lap[4] / 1000.0,
                            'lap_distance': lap_distance,
                            'current_lap_num': display_lap,
                            'raw_current_lap_num': raw_lap_num,
                            'sector': lap[17]
                        }

                
                elif packet_id == 6:
                    offset = HEADER_SIZE + (player_car_index * CAR_TELEM_SIZE)
                    if len(data) >= offset + CAR_TELEM_SIZE:
                        car = struct.unpack(CAR_TELEM_FMT, data[offset:offset+CAR_TELEM_SIZE])
                        
                        telemetry = {
                            'session_time': session_time,
                            'frame_id': frame_id,
                            'speed': car[0],
                            'throttle': car[1],
                            'steer': car[2],
                            'brake': car[3],
                            'gear': car[5],
                            'engine_rpm': car[6],
                            'drs': car[7]
                        }
                        
                        
                        row = {**telemetry, **position_data, **lap_data}
                        
                        
                        if csv_writer is None:
                            csv_handle = open(csv_file, 'w', newline='')
                            csv_writer = csv.DictWriter(csv_handle, fieldnames=row.keys())
                            csv_writer.writeheader()
                        
                        
                        csv_writer.writerow(row)
                        
                        
                        if packet_count % 30 == 0:
                            lap_num = lap_data.get('current_lap_num', 0)
                            lap_dist = lap_data.get('lap_distance', 0)
                            print(f"Lap {lap_num} | Dist: {lap_dist:4.0f}m | Speed: {telemetry['speed']:3d} km/h | Gear: {telemetry['gear']:2d}")

        except socket.timeout:
            if csv_writer and packet_count % 10 == 0:
                csv_handle.flush()  
            pass

except KeyboardInterrupt:
    print("\n\nStopped logging.")
    print(f"Total packets received: {packet_count}")
    print(f"Data saved to: {csv_file}")
    if csv_handle:
        csv_handle.close()
    sock.close()