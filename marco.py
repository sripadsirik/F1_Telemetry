import os
import queue
import threading

from marco_core import (
    COACH_NAME,
    PLOTTING_AVAILABLE,
    SESSION_DATA_DIR,
    TTS_AVAILABLE,
    analyze_session,
    plot_session,
    print_menu,
    run_coaching_session,
    select_session,
    shared_state,
)
from marco_web import WEB_AVAILABLE, WebServer


def main():
    """Main entry point."""
    os.makedirs(SESSION_DATA_DIR, exist_ok=True)

    if not TTS_AVAILABLE:
        print("\n  [!] pyttsx3 not installed - audio coaching disabled")
        print("      Install with: pip install pyttsx3")
    if not PLOTTING_AVAILABLE:
        print("\n  [!] matplotlib not installed - plotting disabled")
        print("      Install with: pip install matplotlib numpy")

    web_server = None
    if WEB_AVAILABLE:
        try:
            web_server = WebServer()
            web_server.start()
        except Exception as e:
            print(f"\n  [!] Web server failed to start: {e}")
            print("      Phone interface will not be available")
    else:
        print("\n  [!] flask/flask-socketio/qrcode not installed - phone interface disabled")
        print("      Install with: pip install flask flask-socketio qrcode[pil] simple-websocket")

    def _phone_command_watcher():
        while True:
            try:
                mode = shared_state['start_queue'].get(timeout=0.5)
            except queue.Empty:
                continue

            if shared_state['session_active']:
                print("\n  [Phone: Session already active]")
                continue

            print(f"\n  [Phone: Starting mode {mode}]")
            run_coaching_session(enable_logging=(mode == 2))

    watcher = threading.Thread(target=_phone_command_watcher, daemon=True)
    watcher.start()

    while True:
        print_menu()

        try:
            choice = input("  Select option: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n  Goodbye!")
            break

        if choice == '1':
            if shared_state['session_active']:
                print("\n  Session already active. Stop current session first.")
                continue
            print("\n  Starting Live Coaching...")
            run_coaching_session(enable_logging=False)

        elif choice == '2':
            if shared_state['session_active']:
                print("\n  Session already active. Stop current session first.")
                continue
            print("\n  Starting Live Coaching with Logging...")
            run_coaching_session(enable_logging=True)

        elif choice == '3':
            session_path = select_session()
            if session_path:
                result = analyze_session(session_path)
                if result and result[2]:
                    df, lap_info, fastest = result
                    show = input("\n  Show visualization? (y/n): ").strip().lower()
                    if show == 'y':
                        plot_session(df, lap_info, fastest['lap_num'], session_path)
                input("\n  Press Enter to continue...")

        elif choice == '4':
            session_path = select_session()
            if session_path:
                result = analyze_session(session_path)
                if result and result[2]:
                    df, lap_info, fastest = result
                    plot_session(df, lap_info, fastest['lap_num'], session_path)
                input("\n  Press Enter to continue...")

        elif choice == '5' or choice.lower() == 'q':
            print("\n  Goodbye!")
            break

        else:
            print("\n  Invalid option")


if __name__ == "__main__":
    main()
