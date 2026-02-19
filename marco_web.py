import logging
import os
import socket
import threading
import time
import json

try:
    from flask import Flask, jsonify, send_from_directory
    from flask_socketio import SocketIO, emit
    import qrcode
    WEB_AVAILABLE = True
except ImportError:
    WEB_AVAILABLE = False

from marco_core import SessionManager, shared_state

WEB_PORT = 5000


class WebServer:
    """Flask web server for phone interface."""

    def __init__(self):
        self.app = None
        self.socketio = None
        self.local_ip = self._get_local_ip()
        self.emitter_thread = None
        self.emitter_running = False
        self.frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'frontend')

    def _get_local_ip(self):
        """Get the local LAN IP address."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            try:
                return socket.gethostbyname(socket.gethostname())
            except Exception:
                return "127.0.0.1"

    def _print_qr_code(self, url):
        """Print scannable QR code in terminal using ANSI colors."""
        try:
            qr = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=1,
                border=2,
            )
            qr.add_data(url)
            qr.make(fit=True)
            matrix = qr.get_matrix()

            # Use ANSI: white bg + black fg for dark modules, white bg + white fg for light
            # This guarantees dark-on-light contrast regardless of terminal theme
            RESET = "\033[0m"
            WHITE_BG = "\033[47m"
            BLACK_ON_WHITE = "\033[30;47m"

            print()
            for row in matrix:
                line = "  " + WHITE_BG
                for cell in row:
                    if cell:
                        line += BLACK_ON_WHITE + "\u2588\u2588"  # dark module
                    else:
                        line += WHITE_BG + "  "                  # light module
                line += RESET
                print(line)
            print()
        except Exception as e:
            print(f"  [QR code generation failed: {e}]")

    def start(self):
        """Start the web server in a background thread."""
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)
        flask_log = logging.getLogger('flask')
        flask_log.setLevel(logging.ERROR)
        engineio_log = logging.getLogger('engineio')
        engineio_log.setLevel(logging.ERROR)
        socketio_log = logging.getLogger('socketio')
        socketio_log.setLevel(logging.ERROR)

        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'marco-f1-engineer'
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", async_mode='threading', logger=False, engineio_logger=False)
        shared_state['socketio'] = self.socketio

        app = self.app
        sio = self.socketio

        def build_state_payload():
            return {
                'active': shared_state['session_active'],
                'track_outline': shared_state['track_outline'],
                'laps': shared_state['lap_times'],
                'x': shared_state['position']['x'],
                'z': shared_state['position']['z'],
                'speed': shared_state['current_speed'],
                'gear': shared_state['current_gear'],
                'lap': shared_state['current_lap_num'],
                'delta': shared_state['current_delta'],
                'sector': shared_state['current_sector'],
                'sector_colors': shared_state['sector_colors'],
                'fastest_lap': shared_state['fastest_lap'],
                'speech_log': shared_state['speech_log'][-20:],
                'bin_meta': shared_state['bin_meta'],
                'reference_bins': shared_state['reference_bins'],
                'current_lap_bins': shared_state['current_lap_bins'],
                'segment_deltas': shared_state['segment_deltas'],
                'last_lap_segment_deltas': shared_state['last_lap_segment_deltas'],
                'heatmap_points': shared_state['heatmap_points'],
                'corner_metrics': shared_state['corner_metrics'],
                'time_loss_summary': shared_state['time_loss_summary'],
                'corner_mastery': shared_state['corner_mastery'],
                'consistency': shared_state['consistency'],
                'driver_profile': shared_state['driver_profile'],
                'skill_scores': shared_state['skill_scores'],
                'optimal_lap': shared_state['optimal_lap'],
                'session_report_summary': shared_state['session_report_summary'],
            }

        @app.route('/')
        def index():
            return send_from_directory(self.frontend_dir, 'index.html')

        @app.route('/assets/<path:filename>')
        def assets(filename):
            return send_from_directory(self.frontend_dir, filename)

        @app.route('/state')
        def state():
            return jsonify(build_state_payload())

        @app.route('/start/<int:mode>', methods=['POST'])
        def start_mode(mode):
            if mode in (1, 2):
                if shared_state['session_active']:
                    return jsonify({'ok': False, 'error': 'Session already active'}), 409
                shared_state['start_queue'].put(mode)
                return jsonify({'ok': True})
            return jsonify({'ok': False, 'error': 'Invalid mode'}), 400

        @app.route('/stop', methods=['POST'])
        def stop_session():
            if shared_state['session_active']:
                shared_state['stop_queue'].put(True)
                return jsonify({'ok': True})
            return jsonify({'ok': False, 'error': 'No active session'}), 409

        @app.route('/sessions')
        def list_sessions():
            mgr = SessionManager()
            sessions = mgr.get_existing_sessions()
            result = []
            for s in sessions[-10:]:
                info = mgr.get_session_info(s['path'])
                report_path = os.path.join(s['path'], 'performance_report.json')
                report_summary = None
                if os.path.exists(report_path):
                    try:
                        with open(report_path, 'r', encoding='utf-8') as f:
                            report = json.load(f)
                        report_summary = {
                            'laps_analyzed': report.get('laps_analyzed'),
                            'best_skill_area': report.get('best_skill_area'),
                            'generated_at': report.get('generated_at'),
                        }
                    except Exception:
                        report_summary = None
                result.append({
                    'folder': s['folder'],
                    'path': s['path'],
                    'num_laps': info['num_laps'] if info else 0,
                    'report_available': os.path.exists(report_path),
                    'report_summary': report_summary,
                })
            return jsonify(result)

        @app.route('/session/<session_id>/report')
        def session_report(session_id):
            safe_session_id = os.path.basename(session_id)
            report_path = os.path.join(SessionManager().base_dir, safe_session_id, 'performance_report.json')
            if not os.path.exists(report_path):
                return jsonify({'ok': False, 'error': 'Report not found'}), 404
            try:
                with open(report_path, 'r', encoding='utf-8') as f:
                    report = json.load(f)
                return jsonify({'ok': True, 'report': report})
            except Exception as exc:
                return jsonify({'ok': False, 'error': str(exc)}), 500

        @sio.on('connect')
        def handle_connect():
            emit('session_state', build_state_payload())

        self.emitter_running = True
        self.emitter_thread = threading.Thread(target=self._telemetry_emitter, daemon=True)
        self.emitter_thread.start()

        url = f"http://{self.local_ip}:{WEB_PORT}"

        print(f"\n  {'='*50}")
        print("  PHONE REMOTE CONTROL")
        print(f"  {'='*50}")
        print("  Scan QR code with your phone:")
        self._print_qr_code(url)
        print(f"  Or open: {url}")
        print(f"  {'='*50}\n")

        server_thread = threading.Thread(
            target=lambda: sio.run(app, host='0.0.0.0', port=WEB_PORT, use_reloader=False, log_output=False),
            daemon=True,
        )
        server_thread.start()

    def _telemetry_emitter(self):
        """Emit telemetry data to connected web clients."""
        while self.emitter_running:
            try:
                if self.socketio and shared_state['session_active']:
                    self.socketio.emit('telemetry', {
                        'x': shared_state['position']['x'],
                        'z': shared_state['position']['z'],
                        'speed': shared_state['current_speed'],
                        'gear': shared_state['current_gear'],
                        'lap': shared_state['current_lap_num'],
                        'delta': round(shared_state['current_delta'], 3),
                        'sector': shared_state['current_sector'],
                        'sector_colors': shared_state['sector_colors'],
                        'fastest_lap': shared_state['fastest_lap'],
                    }, namespace='/')
            except Exception:
                pass
            time.sleep(0.01)  # keep same smoothness as current setup
