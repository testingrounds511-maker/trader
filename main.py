"""Phantom Trader v3 — FundedNext Free Trial Edition.

Entry point. Launches dashboard or runs in CLI mode.
"""

import argparse
import os
import subprocess
import sys


def check_config():
    """Validate configuration before starting."""
    from config import config
    errors = config.validate()
    if errors:
        print("\n❌ Configuration errors:")
        for e in errors:
            print(f"   → {e}")
        print("\n   Copy .env.example to .env and fill in your credentials.\n")
        return False
    print("✅ Configuration OK")
    if config.manual_mode:
        print("   Mode: MANUAL CONFIRM (recommended for FundedNext)")
    else:
        print("   Mode: AUTO EXECUTE (⚠️ may conflict with FN EA rules)")
    return True


def ensure_data_dir():
    os.makedirs("data", exist_ok=True)


def main():
    parser = argparse.ArgumentParser(
        description="👻 Phantom Trader v3 — FundedNext Free Trial Edition"
    )
    parser.add_argument("--check", action="store_true", help="Validate config only")
    parser.add_argument("--manual", action="store_true", help="Force manual mode")
    parser.add_argument("--auto", action="store_true", help="Force auto mode")
    parser.add_argument("--cli", action="store_true", help="Run in CLI (no dashboard)")
    args = parser.parse_args()

    if args.check:
        check_config()
        return

    if not check_config():
        sys.exit(1)

    ensure_data_dir()

    # Override execution mode
    from config import config
    if args.manual:
        config.manual_mode = True
    elif args.auto:
        config.manual_mode = False

    if args.cli:
        print("\n👻 Phantom Trader v3 — CLI Mode")
        print("=" * 50)
        from bot.engine import TradingEngine
        engine = TradingEngine()
        try:
            engine.start()
            import time
            while engine.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Stopping...")
            engine.stop()
        return

    # Launch Streamlit dashboard
    print("\n🚀 Starting Phantom Trader v3 Dashboard...")
    print("   → Open http://localhost:8501 in your browser")
    print("   → Press Ctrl+C to stop\n")

    dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard", "app.py")
    subprocess.run([
        sys.executable, "-m", "streamlit", "run",
        dashboard_path,
        "--server.port", "8501",
        "--server.headless", "true",
        "--theme.base", "dark",
        "--theme.primaryColor", "#00ff88",
        "--theme.backgroundColor", "#0a0e17",
        "--theme.secondaryBackgroundColor", "#0d1421",
        "--theme.textColor", "#e0e6ed",
    ])


if __name__ == "__main__":
    main()
