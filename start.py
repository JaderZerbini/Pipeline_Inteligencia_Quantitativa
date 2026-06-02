import subprocess, sys, os, time, logging, signal

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [STARTER] %(message)s")
logger = logging.getLogger(__name__)

PORT = os.environ.get("PORT", "8080")

PROCESSES = {
    "web": [
        sys.executable, "-m", "streamlit", "run",
        "dashboard/app.py",
        "--server.port", PORT,
        "--server.address", "0.0.0.0",
        "--server.headless", "true",
    ],
    "crypto": [sys.executable, "crypto/scheduler.py"],
    "b3":     [sys.executable, "b3/scheduler.py"],
}

running = {}

def start_process(name):
    logger.info(f"Iniciando processo: {name}")
    p = subprocess.Popen(PROCESSES[name])
    running[name] = p
    return p

def shutdown(sig, frame):
    logger.info("Encerrando todos os processos...")
    for name, p in running.items():
        logger.info(f"Parando {name} (pid={p.pid})")
        p.terminate()
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)

# Start all processes
for name in PROCESSES:
    start_process(name)

logger.info("Todos os processos iniciados. Monitorando...")

# Monitor and restart if any dies
while True:
    time.sleep(10)
    for name, p in list(running.items()):
        if p.poll() is not None:
            logger.warning(
                f"Processo {name} morreu (código {p.returncode}) — reiniciando..."
            )
            start_process(name)
