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
current_udp_lap = 0
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
                        udp_lap = lap[14]
                        display_lap = udp_lap - 1  # UDP lap 2 = game Lap 1

                        if udp_lap != current_udp_lap:
                            if display_lap >= 1:
                                last_time = lap[0] / 1000.0
                                time_str = f" (Lap {display_lap - 1}: {last_time:.3f}s)" if last_time > 0 else ""
                                print(f"\n>>> LAP {display_lap} STARTED <<<{time_str}")
                            current_udp_lap = udp_lap

                        lap_data = {
                            'last_lap_time': lap[0] / 1000.0,
                            'current_lap_time': lap[1] / 1000.0,
                            'sector1_time': lap[2] / 1000.0,
                            'sector2_time': lap[4] / 1000.0,
                            'lap_distance': lap[10],
                            'current_lap_num': display_lap,
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