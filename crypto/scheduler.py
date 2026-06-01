"""
crypto_scheduler.py
-------------------
Roda o pipeline cripto automaticamente a cada 6 horas.
Execute uma vez e deixe rodando em segundo plano:
  .\venv\Scripts\python.exe crypto_scheduler.py

Para parar: Ctrl+C no terminal onde está rodando.

Por que 6 horas?
- Gera ~4 execuções por dia
- Respeita o rate limit do CoinGecko
- Acumula dados suficientes para o período de observação
  sem gastar créditos do OpenRouter desnecessariamente
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
        logging.FileHandler(os.path.join(_LOG_BASE, "scheduler.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

INTERVAL_HOURS = 6
INTERVAL_SECONDS = INTERVAL_HOURS * 3600


def run_pipeline():
    """Executa crypto_main.py e retorna True se bem-sucedido."""
    logger.info("=" * 50)
    logger.info("SCHEDULER: iniciando execução do pipeline cripto")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main_path = os.path.join(root, "crypto_main.py")
    try:
        result = subprocess.run(
            [sys.executable, main_path],
            capture_output=False,   # mostra output em tempo real
            timeout=300,            # 5 minutos máximo
            cwd=root,
        )
        if result.returncode == 0:
            logger.info("SCHEDULER: pipeline concluído com sucesso")
            return True
        else:
            logger.error(f"SCHEDULER: pipeline terminou com código {result.returncode}")
            return False
    except subprocess.TimeoutExpired:
        logger.error("SCHEDULER: pipeline excedeu 5 minutos — interrompido")
        return False
    except Exception as e:
        logger.error(f"SCHEDULER: erro inesperado — {e}")
        return False


def next_run_str(next_dt):
    brt = next_dt - timedelta(hours=3)
    return brt.strftime("%d/%m %H:%M") + " BRT"


if __name__ == "__main__":
    logger.info(f"SCHEDULER iniciado — executando a cada {INTERVAL_HOURS}h")
    logger.info("Pressione Ctrl+C para parar\n")

    # Roda imediatamente na inicialização
    run_pipeline()

    while True:
        next_run = datetime.now(timezone.utc) + timedelta(seconds=INTERVAL_SECONDS)
        logger.info(f"SCHEDULER: próxima execução em {next_run_str(next_run)}")

        try:
            time.sleep(INTERVAL_SECONDS)
        except KeyboardInterrupt:
            logger.info("SCHEDULER: parado pelo usuário")
            break

        run_pipeline()
