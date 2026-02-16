import socket
import struct


UDP_IP = "0.0.0.0"
UDP_PORT = 20777


sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
sock.settimeout(1.0)

print(f"Listening for F1 25 telemetry on {UDP_IP}:{UDP_PORT}")
print("Make sure F1 25 telemetry is enabled and you're in a session!")
print("-" * 60)


HEADER_FMT = '<HBBBBBQfIIBB'
HEADER_SIZE = struct.calcsize(HEADER_FMT)  

CAR_TELEM_FMT = '<HfffBbHBBHHHHHBBBBBBBBHffffBBBB'
CAR_TELEM_SIZE = struct.calcsize(CAR_TELEM_FMT) 

packet_count = 0

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

                
                if packet_id == 6:
                    offset = HEADER_SIZE + (player_car_index * CAR_TELEM_SIZE)

                    if len(data) >= offset + CAR_TELEM_SIZE:
                        car = struct.unpack(CAR_TELEM_FMT, data[offset:offset + CAR_TELEM_SIZE])
                        speed = car[0]
                        throttle = car[1]
                        steer = car[2]
                        brake = car[3]
                        gear = car[5]
                        engine_rpm = car[6]

                        if packet_count % 10 == 0:
                            print(f"Speed: {speed:3d} km/h | Throttle: {throttle:.2f} | Brake: {brake:.2f} | Gear: {gear:2d} | RPM: {engine_rpm:5d}")

        except socket.timeout:
            print("Waiting for packets...")

except KeyboardInterrupt:
    print("\n\nStopped listening.")
    print(f"Total packets received: {packet_count}")
    sock.close()
