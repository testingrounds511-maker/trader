"""Phantom Wolf v3.6 — Quantum Predator Entry Point.

Usage:
    python wolf_main.py

Starts the async trading engine with all v3.6 modules.
Press Ctrl+C for graceful shutdown.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Ensure data directory exists
Path("data").mkdir(exist_ok=True)

# ── Logging Setup ──
LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"
)
LOG_FILE = "data/wolf_engine.log"


def setup_logging():
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(LOG_FORMAT, datefmt="%H:%M:%S"))
    root.addHandler(console)

    # File handler (rotating-friendly)
    try:
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
        )
        root.addHandler(file_handler)
    except Exception:
        pass  # If log file can't be created, continue with console only

    # Suppress noisy libraries
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def validate_environment():
    """Validate required environment variables before starting."""
    from config import config

    errors = config.validate()
    if errors:
        for e in errors:
            print(f"  CONFIG ERROR: {e}")
        print("\nPlease check your .env file and try again.")
        sys.exit(1)

    # Log configuration summary
    logger = logging.getLogger("phantom.wolf")
    logger.info("=" * 60)
    logger.info("PHANTOM WOLF v3.6 — Quantum Predator Edition")
    logger.info("=" * 60)
    logger.info(f"  Mode: {'PAPER' if config.is_paper else 'LIVE'}")
    logger.info(f"  Profile: {config.risk_profile}")
    logger.info(f"  Initial Capital: ${config.initial_capital_usd:.2f}")
    logger.info(f"  Capital Base Mode: {config.capital_base_mode}")
    logger.info(f"  Slippage Tolerance: {config.max_slippage_tolerance_pct:.3%}")
    logger.info(f"  Crypto Pairs: {len(config.crypto_pairs)}")
    logger.info(f"  Stock Symbols: {len(config.stock_symbols)}")
    logger.info(f"  Cycle Interval: {config.check_interval} min")
    logger.info(f"  Groq NLP: {'enabled' if config.has_groq else 'disabled'}")
    if config.has_groq:
        logger.info(f"  Groq Model: {config.groq_model}")
        logger.info(f"  NLP Conf Min: {config.nlp_action_confidence_min:.2f}")
    logger.info(f"  Quiver (Congress): {'enabled' if config.has_quiver else 'disabled'}")
    logger.info(f"  Finnhub: {'enabled' if config.has_finnhub else 'disabled'}")
    logger.info(f"  Aggression Boost: {config.aggression_boost_pct:.0%}")
    logger.info(
        f"  Entry/Wolf Thresholds: min_conf={config.min_entry_confidence:.2f} "
        f"| wolf_conf={config.wolf_mode_confidence:.2f}"
    )
    logger.info("=" * 60)


async def main():
    """Async entry point."""
    from wolf_engine import PhantomWolfEngine

    engine = PhantomWolfEngine()

    try:
        await engine.run()
    except KeyboardInterrupt:
        logging.getLogger("phantom.wolf").info("Interrupted by user")
    except SystemExit:
        pass  # Terminal breaker calls sys.exit


if __name__ == "__main__":
    setup_logging()
    validate_environment()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nPhantom Wolf shutdown complete.")
