import logging
import os
import socket
import sys
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

from marco_core import SessionManager, shared_state, analyze_session, plot_session

WEB_PORT = 5000

# ---------------------------------------------------------------------------
# Resolve base directory — works both from source and PyInstaller bundle.
# ---------------------------------------------------------------------------
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    _BASE_DIR = sys._MEIPASS          # type: ignore[attr-defined]
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_FRONTEND_DIST   = os.path.join(_BASE_DIR, 'frontend', 'dist')


# ---------------------------------------------------------------------------
# State payload builder — module-level so both start() and _telemetry_emitter
# can call it without closure tricks.
# ---------------------------------------------------------------------------
_MAX_HEATMAP_PTS = 8_000   # ~1 lap of high-res trail is plenty; canvas uses
                            # track_outline for the heatmap once it's available.

def _build_state_payload() -> dict:
    # Downsample heatmap_points so the payload stays small after many laps.
    hp: list = shared_state['heatmap_points']
    if len(hp) > _MAX_HEATMAP_PTS:
        step = max(1, len(hp) // _MAX_HEATMAP_PTS)
        hp = hp[::step]

    return {
        'active':                  shared_state['session_active'],
        'track_outline':           shared_state['track_outline'],
        'laps':                    shared_state['lap_times'],
        'x':                       shared_state['position']['x'],
        'z':                       shared_state['position']['z'],
        'speed':                   shared_state['current_speed'],
        'gear':                    shared_state['current_gear'],
        'lap':                     shared_state['current_lap_num'],
        'delta':                   shared_state['current_delta'],
        'sector':                  shared_state['current_sector'],
        'sector_colors':           shared_state['sector_colors'],
        'fastest_lap':             shared_state['fastest_lap'],
        'speech_log':              shared_state['speech_log'][-20:],
        'bin_meta':                shared_state['bin_meta'],
        'reference_bins':          shared_state['reference_bins'],
        'current_lap_bins':        shared_state['current_lap_bins'],
        'segment_deltas':          shared_state['segment_deltas'],
        'last_lap_segment_deltas': shared_state['last_lap_segment_deltas'],
        'heatmap_points':          hp,
        'corner_metrics':          shared_state['corner_metrics'],
        'time_loss_summary':       shared_state['time_loss_summary'],
        'corner_mastery':          shared_state['corner_mastery'],
        'consistency':             shared_state['consistency'],
        'driver_profile':          shared_state['driver_profile'],
        'skill_scores':            shared_state['skill_scores'],
        'optimal_lap':             shared_state['optimal_lap'],
        'session_report_summary':  shared_state['session_report_summary'],
    }


class WebServer:
    """Flask web server for phone interface."""

    def __init__(self):
        self.app = None
        self.socketio = None
        self.local_ip = self._get_local_ip()
        self.emitter_thread = None
        self.emitter_running = False
        self.frontend_dir = _FRONTEND_DIST

    def _get_local_ip(self):
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

            RESET        = "\033[0m"
            WHITE_BG     = "\033[47m"
            BLACK_ON_WHITE = "\033[30;47m"

            print()
            for row in matrix:
                line = "  " + WHITE_BG
                for cell in row:
                    line += (BLACK_ON_WHITE + "\u2588\u2588") if cell else (WHITE_BG + "  ")
                line += RESET
                print(line)
            print()
        except Exception as e:
            print(f"  [QR code generation failed: {e}]")

    def start(self):
        """Start the web server in a background thread."""
        for name in ('werkzeug', 'flask', 'engineio', 'socketio'):
            logging.getLogger(name).setLevel(logging.ERROR)

        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'marco-f1-engineer'
        self.socketio = SocketIO(
            self.app,
            cors_allowed_origins="*",
            async_mode='threading',
            logger=False,
            engineio_logger=False,
        )
        shared_state['socketio'] = self.socketio

        app = self.app
        sio = self.socketio
        frontend_dir = self.frontend_dir

        # ── static assets ───────────────────────────────────────────────────
        @app.route('/assets/<path:filename>')
        def assets(filename):
            return send_from_directory(os.path.join(frontend_dir, 'assets'), filename)

        # ── API ─────────────────────────────────────────────────────────────
        @app.route('/state')
        def state():
            return jsonify(_build_state_payload())

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
                        pass
                result.append({
                    'folder': s['folder'],
                    'path': s['path'],
                    'num_laps': info['num_laps'] if info else 0,
                    'report_available': os.path.exists(report_path),
                    'report_summary': report_summary,
                })
            return jsonify(result)

        @app.route('/session/<session_id>/track-data')
        def session_track_data(session_id):
            safe_id = os.path.basename(session_id)
            base = SessionManager().base_dir
            folder = os.path.join(base, safe_id)
            if not os.path.isdir(folder):
                return jsonify({'ok': False, 'error': 'Session not found'}), 404
            try:
                import pandas as pd  # lazy import — already a dep via marco_core
                result: dict = {'ok': True, 'folder': safe_id}

                # ── reference lap → track outline + heatmap ──────────────────
                ref_path = os.path.join(folder, 'reference_lap.csv')
                track_outline: list = []
                heatmap: list = []
                if os.path.exists(ref_path):
                    ref = pd.read_csv(ref_path)
                    step = max(1, len(ref) // 3000)
                    s = ref.iloc[::step].copy()
                    for col in ('speed', 'throttle', 'brake', 'pos_x', 'pos_z'):
                        if col in s.columns:
                            s[col] = s[col].fillna(0)
                    track_outline = [
                        [float(r.pos_x), float(r.pos_z)]
                        for r in s.itertuples()
                    ]
                    heatmap = [
                        {
                            'x': float(r.pos_x), 'z': float(r.pos_z),
                            'speed': float(r.speed),
                            'throttle': float(r.throttle),
                            'brake': float(r.brake),
                        }
                        for r in s.itertuples()
                    ]
                result['track_outline'] = track_outline
                result['heatmap'] = heatmap

                # ── lap list from telemetry ───────────────────────────────────
                tel_path = os.path.join(folder, 'telemetry.csv')
                laps: list = []
                if os.path.exists(tel_path):
                    needed = ['session_time', 'last_lap_time', 'lap_invalid', 'current_lap_num']
                    tel = pd.read_csv(tel_path, usecols=needed)
                    tel = tel.sort_values('session_time').reset_index(drop=True)
                    tel['_prev'] = tel['last_lap_time'].shift(1).fillna(0)
                    completions = tel[
                        (tel['last_lap_time'] > 0) &
                        ((tel['last_lap_time'] - tel['_prev']).abs() > 0.001)
                    ]
                    for i, (_, row) in enumerate(completions.iterrows()):
                        laps.append({
                            'lap_num': i + 1,
                            'time': round(float(row['last_lap_time']), 3),
                            'valid': not bool(row['lap_invalid']),
                        })
                result['laps'] = laps
                valid_times = [l['time'] for l in laps if l['valid']]
                result['pb_time'] = min(valid_times) if valid_times else None

                # ── performance report ────────────────────────────────────────
                report_path = os.path.join(folder, 'performance_report.json')
                result['report'] = None
                if os.path.exists(report_path):
                    with open(report_path, 'r', encoding='utf-8') as f:
                        result['report'] = json.load(f)

                return jsonify(result)
            except Exception as exc:
                return jsonify({'ok': False, 'error': str(exc)}), 500

        @app.route('/session/<session_id>/open-folder', methods=['POST'])
        def open_session_folder(session_id):
            safe_id = os.path.basename(session_id)
            folder_path = os.path.join(SessionManager().base_dir, safe_id)
            if not os.path.isdir(folder_path):
                return jsonify({'ok': False, 'error': 'Folder not found'}), 404
            try:
                os.startfile(folder_path)  # Windows Explorer
                return jsonify({'ok': True})
            except Exception as exc:
                return jsonify({'ok': False, 'error': str(exc)}), 500

        @app.route('/session/<session_id>/save-plot', methods=['POST'])
        def save_session_plot(session_id):
            safe_id = os.path.basename(session_id)
            folder = os.path.join(SessionManager().base_dir, safe_id)
            if not os.path.isdir(folder):
                return jsonify({'ok': False, 'error': 'Session not found'}), 404
            try:
                result = analyze_session(folder)
                if not result or not result[2]:
                    return jsonify({'ok': False, 'error': 'Analysis failed or no valid laps found'}), 500
                df, lap_info, fastest = result
                plot_session(df, lap_info, fastest['lap_num'], folder, show=False)
                return jsonify({'ok': True})
            except Exception as exc:
                return jsonify({'ok': False, 'error': str(exc)}), 500

        @app.route('/session/<session_id>/report')
        def session_report(session_id):
            safe_id = os.path.basename(session_id)
            report_path = os.path.join(
                SessionManager().base_dir, safe_id, 'performance_report.json'
            )
            if not os.path.exists(report_path):
                return jsonify({'ok': False, 'error': 'Report not found'}), 404
            try:
                with open(report_path, 'r', encoding='utf-8') as f:
                    report = json.load(f)
                return jsonify({'ok': True, 'report': report})
            except Exception as exc:
                return jsonify({'ok': False, 'error': str(exc)}), 500

        # ── Socket.IO ───────────────────────────────────────────────────────
        @sio.on('connect')
        def handle_connect():
            # Send full state immediately so the new client is up-to-date.
            emit('session_state', _build_state_payload())

        # ── Legacy UI (iOS 12 / old Safari) ─────────────────────────────────
        # ── SPA fallback ────────────────────────────────────────────────────
        @app.route('/')
        def index():
            return send_from_directory(frontend_dir, 'index.html')

        @app.route('/<path:path>')
        def spa_fallback(path):
            full = os.path.join(frontend_dir, path)
            if os.path.isfile(full):
                return send_from_directory(frontend_dir, path)
            return send_from_directory(frontend_dir, 'index.html')

        # ── start emitter ───────────────────────────────────────────────────
        self.emitter_running = True
        self.emitter_thread = threading.Thread(
            target=self._telemetry_emitter, daemon=True
        )
        self.emitter_thread.start()

        url = f"http://{self.local_ip}:{WEB_PORT}"
        print(f"\n  {'='*50}")
        print("  PHONE REMOTE CONTROL")
        print(f"  {'='*50}")
        print("  Scan QR code with your phone:")
        self._print_qr_code(url)
        print(f"  Or open: {url}")
        print(f"  {'='*50}\n")

        if not os.path.isdir(frontend_dir):
            print(f"  [!] Frontend build not found at: {frontend_dir}")
            print("      Run:  cd frontend && npm install && npm run build")

        server_thread = threading.Thread(
            target=lambda: sio.run(
                app, host='0.0.0.0', port=WEB_PORT,
                use_reloader=False, log_output=False,
            ),
            daemon=True,
        )
        server_thread.start()

    # ── emitter ─────────────────────────────────────────────────────────────
    def _telemetry_emitter(self):
        """
        Two-speed push to connected clients:
          • Fast  (10 ms)  — car position, speed, gear, delta, sector  [telemetry]
          • Slow  (1 s)    — full analytics state (laps, cards, speech) [session_state]

        The fast event keeps the track map and HUD silky-smooth.
        The slow event ensures lap times, corner mastery, consistency, etc.
        refresh automatically without the user having to reload.
        """
        last_full_emit = 0.0

        while self.emitter_running:
            try:
                sio = self.socketio
                if sio:
                    active = shared_state['session_active']
                    now = time.monotonic()

                    # ── fast: car telemetry (always, so idle screen stays live) ──
                    if active:
                        sio.emit('telemetry', {
                            'x':            shared_state['position']['x'],
                            'z':            shared_state['position']['z'],
                            'speed':        shared_state['current_speed'],
                            'gear':         shared_state['current_gear'],
                            'lap':          shared_state['current_lap_num'],
                            'delta':        round(shared_state['current_delta'], 3),
                            'sector':       shared_state['current_sector'],
                            'sector_colors': shared_state['sector_colors'],
                            'fastest_lap':  shared_state['fastest_lap'],
                        }, namespace='/')

                    # ── slow: full analytics state every 1 s ──────────────────
                    #   Active session  → 1 s   (lap times, cards update after each lap)
                    #   Idle            → 5 s   (just in case something changes)
                    full_interval = 1.0 if active else 5.0
                    if now - last_full_emit >= full_interval:
                        sio.emit('session_state', _build_state_payload(), namespace='/')
                        last_full_emit = now

            except Exception:
                pass

            time.sleep(0.01)
