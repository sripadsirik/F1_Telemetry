import socket
import struct
import csv
from datetime import datetime
import os

# F1 25 UDP Settings
UDP_IP = "0.0.0.0"
UDP_PORT = 20777

# Create UDP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
sock.settimeout(1.0)

# F1 25 packet formats
HEADER_FMT = '<HBBBBBQfIIBB'
HEADER_SIZE = struct.calcsize(HEADER_FMT)

CAR_TELEM_FMT = '<HfffBbHBBHHHHHBBBBBBBBHffffBBBB'
CAR_TELEM_SIZE = struct.calcsize(CAR_TELEM_FMT)

# Motion packet format (Packet ID 0)
# worldPositionX/Y/Z, worldVelocityX/Y/Z, etc.
MOTION_FMT = '<fffhhh' + 'hhh' + 'hhh' + 'hhh' + 'hhh'  # First car only for now
MOTION_SIZE = struct.calcsize(MOTION_FMT)

# Lap data packet format (Packet ID 2) - F1 25
# lastLapTime(I) currentLapTime(I) sector1MS(H) sector1Min(B)
# sector2MS(H) sector2Min(B) deltaToFrontMS(H) deltaToFrontMin(B)
# deltaToLeaderMS(H) deltaToLeaderMin(B) lapDistance(f) totalDistance(f)
# safetyCarDelta(f) carPosition(B) currentLapNum(B) pitStatus(B)
# numPitStops(B) sector(B) currentLapInvalid(B) penalties(B)
# totalWarnings(B) cornerCuttingWarnings(B) numUnservedDriveThrough(B)
# numUnservedStopGo(B) gridPosition(B) driverStatus(B) resultStatus(B)
# pitLaneTimerActive(B) pitLaneTimeInLaneMS(H) pitStopTimerMS(H)
# pitStopShouldServePen(B) speedTrapFastestSpeed(f) speedTrapFastestLap(B)
LAP_DATA_FMT = '<IIHBHBHBHBfffBBBBBBBBBBBBBBHHBfB'
LAP_DATA_SIZE = struct.calcsize(LAP_DATA_FMT)

# Create logs directory
os.makedirs('logs', exist_ok=True)

# Create CSV file
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
csv_file = f'logs/telemetry_{timestamp}.csv'
csv_writer = None
csv_handle = None

print(f"Logging telemetry to: {csv_file}")
print(f"Listening on {UDP_IP}:{UDP_PORT}")
print("Start driving in F1 25!")
print("-" * 60)

packet_count = 0
current_lap = 0
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

                # Packet ID 0 = Motion (position data)
                if packet_id == 0 and len(data) >= HEADER_SIZE + MOTION_SIZE:
                    offset = HEADER_SIZE + (player_car_index * 60)  # 60 bytes per car in motion
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

                # Packet ID 2 = Lap Data
                elif packet_id == 2:
                    offset = HEADER_SIZE + (player_car_index * LAP_DATA_SIZE)
                    if len(data) >= offset + LAP_DATA_SIZE:
                        lap = struct.unpack(LAP_DATA_FMT, data[offset:offset+LAP_DATA_SIZE])
                        lap_data = {
                            'last_lap_time': lap[0] / 1000.0,
                            'current_lap_time': lap[1] / 1000.0,
                            'sector1_time': lap[2] / 1000.0,
                            'sector2_time': lap[4] / 1000.0,
                            'lap_distance': lap[10],
                            'current_lap_num': lap[14],
                            'sector': lap[17]
                        }
                        
                        # Detect new lap
                        if lap_data['current_lap_num'] != current_lap:
                            print(f"\n>>> LAP {lap_data['current_lap_num']} STARTED <<<")
                            current_lap = lap_data['current_lap_num']

                # Packet ID 6 = Car Telemetry
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
                        
                        # Merge all data
                        row = {**telemetry, **position_data, **lap_data}
                        
                        # Initialize CSV writer on first data
                        if csv_writer is None:
                            csv_handle = open(csv_file, 'w', newline='')
                            csv_writer = csv.DictWriter(csv_handle, fieldnames=row.keys())
                            csv_writer.writeheader()
                        
                        # Write row
                        csv_writer.writerow(row)
                        
                        # Print every 30 packets
                        if packet_count % 30 == 0:
                            lap_num = lap_data.get('current_lap_num', 0)
                            lap_dist = lap_data.get('lap_distance', 0)
                            print(f"Lap {lap_num} | Dist: {lap_dist:4.0f}m | Speed: {telemetry['speed']:3d} km/h | Gear: {telemetry['gear']:2d}")

        except socket.timeout:
            if csv_writer and packet_count % 10 == 0:
                csv_handle.flush()  # Save data periodically
            pass

except KeyboardInterrupt:
    print("\n\nStopped logging.")
    print(f"Total packets received: {packet_count}")
    print(f"Data saved to: {csv_file}")
    if csv_handle:
        csv_handle.close()
    sock.close()