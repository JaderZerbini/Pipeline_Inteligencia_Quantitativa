"""
b3/scheduler.py
---------------
Roda o pipeline B3 automaticamente durante o pregão da B3.

Horário do pregão: 10:00 - 17:30 BRT (UTC-3) = 13:00 - 20:30 UTC
Intervalo: a cada 30 minutos durante o pregão
Fora do pregão: aguarda, não consome créditos de IA

Uso:
  python b3/scheduler.py
"""

import os
import subprocess
import sys
import time
import logging
from datetime import datetime, timezone, timedelta

# Railway mounts persistent volume at /data; locally use data/
_LOG_BASE = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "data")
os.makedirs(_LOG_BASE, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(_LOG_BASE, "b3_scheduler.log"),
            encoding="utf-8"
        ),
    ],
)
logger = logging.getLogger(__name__)

INTERVAL_MINUTES = 30
MARKET_OPEN_UTC  = 13   # 10:00 BRT = 13:00 UTC
MARKET_CLOSE_UTC = 21   # 17:30 BRT = 20:30 UTC ≈ 21:00 UTC (margem)
MARKET_DAYS = [0, 1, 2, 3, 4]  # Segunda a sexta


def is_market_open() -> bool:
    """Returns True if B3 is currently open."""
    now = datetime.now(timezone.utc)
    if now.weekday() not in MARKET_DAYS:
        return False
    return MARKET_OPEN_UTC <= now.hour < MARKET_CLOSE_UTC


def run_b3_pipeline():
    """Executes main.py once."""
    logger.info("B3 SCHEDULER: iniciando pipeline B3...")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main_path = os.path.join(root, "main.py")
    try:
        result = subprocess.run(
            [sys.executable, main_path],
            capture_output=False,
            timeout=600,  # 10 minutes max
            cwd=root,
        )
        if result.returncode == 0:
            logger.info("B3 SCHEDULER: pipeline concluído com sucesso")
        else:
            logger.error(f"B3 SCHEDULER: pipeline terminou com código {result.returncode}")
    except subprocess.TimeoutExpired:
        logger.error("B3 SCHEDULER: timeout após 10 minutos")
    except Exception as e:
        logger.error(f"B3 SCHEDULER: erro — {e}")


def next_check_str():
    now = datetime.now(timezone.utc)
    next_run = now + timedelta(minutes=INTERVAL_MINUTES)
    brt = next_run - timedelta(hours=3)
    return brt.strftime("%d/%m %H:%M") + " BRT"


if __name__ == "__main__":
    logger.info(f"B3 SCHEDULER iniciado — verifica pregão a cada {INTERVAL_MINUTES}min")
    logger.info("Pregão B3: 10:00-17:30 BRT (seg-sex)")

    while True:
        if is_market_open():
            run_b3_pipeline()
        else:
            now_brt = datetime.now(timezone.utc) - timedelta(hours=3)
            logger.info(
                f"B3 SCHEDULER: fora do pregão ({now_brt.strftime('%a %H:%M')} BRT) — aguardando"
            )

        logger.info(f"B3 SCHEDULER: próxima verificação em {next_check_str()}")
        time.sleep(INTERVAL_MINUTES * 60)
