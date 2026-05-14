import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List

import docker
from docker.models.containers import Container

logger = logging.getLogger(__name__)

# --- Configuração via env vars ---
WORKER_IMAGE = os.getenv("WORKER_IMAGE", "mini-cloud-worker:latest")
WORKER_NETWORK = os.getenv("WORKER_NETWORK", "mini-cloud-project_default")
MIN_WORKERS = int(os.getenv("MIN_WORKERS", "1"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "5"))
SCALE_UP_THRESHOLD = float(os.getenv("SCALE_UP_THRESHOLD", "60"))
SCALE_DOWN_THRESHOLD = float(os.getenv("SCALE_DOWN_THRESHOLD", "20"))
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "30"))
CHECK_INTERVAL = 10  # segundos entre verificações


@dataclass
class WorkerInfo:
    container_id: str
    name: str
    address: str          # ex: "worker-3:8001"
    cpu_percent: float = 0.0
    mem_percent: float = 0.0
    last_seen: float = field(default_factory=time.time)


class ElasticityEngine:
    """
    Loop de controlo reativo:
        1. Lê CPU/RAM de todos os workers (Metric Source).
        2. Calcula média e decide (Decision Engine).
        3. Cria/destrói containers via Docker SDK (Actuator).
    """

    def __init__(self):
        self._client: docker.DockerClient | None = None
        self.workers: Dict[str, WorkerInfo] = {}
        self.last_scale_action: float = 0.0  # timestamp para cooldown
        self._running = False

    @property
    def client(self) -> docker.DockerClient:
        if self._client is None:
            # timeout=10 prevents hanging forever when the socket is slow or missing
            self._client = docker.from_env(timeout=10)
        return self._client

    # ---------- Metric Source ----------

    def _calc_cpu_percent(self, stats: dict) -> float:
        """Fórmula oficial usada pelo `docker stats`."""
        try:
            cpu = stats["cpu_stats"]
            pre = stats["precpu_stats"]
            cpu_delta = cpu["cpu_usage"]["total_usage"] - pre["cpu_usage"]["total_usage"]
            sys_delta = cpu["system_cpu_usage"] - pre["system_cpu_usage"]
            online = cpu.get("online_cpus") or len(cpu["cpu_usage"].get("percpu_usage", [1]))
            if sys_delta > 0 and cpu_delta > 0:
                return (cpu_delta / sys_delta) * 100.0
        except (KeyError, TypeError):
            pass
        return 0.0

    @staticmethod
    def _container_address(c, port: int = 8001) -> str:
        """
        Prefer the container's IP on the shared network over its hostname.
        Name-based DNS is unreliable on Docker Desktop for Windows when
        containers start at different times; the IP is always authoritative.
        Falls back to the container name if no IP is found.
        """
        for net in c.attrs.get("NetworkSettings", {}).get("Networks", {}).values():
            ip = net.get("IPAddress")
            if ip:
                return f"{ip}:{port}"
        return f"{c.name}:{port}"

    def collect_metrics(self) -> List[WorkerInfo]:
        """Refresca o cache de métricas para todos os workers vivos."""
        containers = self.client.containers.list(
            filters={"label": "role=worker"}
        )
        for c in containers:
            c.reload()  # ensure NetworkSettings is populated
            stats = c.stats(stream=False)
            cpu = self._calc_cpu_percent(stats)
            mem_usage = stats["memory_stats"].get("usage", 0)
            mem_limit = stats["memory_stats"].get("limit", 1)
            mem_pct = (mem_usage / mem_limit) * 100 if mem_limit else 0
            self.workers[c.id] = WorkerInfo(
                container_id=c.id,
                name=c.name,
                address=self._container_address(c),
                cpu_percent=cpu,
                mem_percent=mem_pct,
            )
        # Remover workers que já não existem
        live_ids = {c.id for c in containers}
        for dead in [wid for wid in self.workers if wid not in live_ids]:
            del self.workers[dead]
        return list(self.workers.values())

    # ---------- Actuator ----------

    def _spawn_worker(self) -> Container:
        """Cria um novo worker. Nome único, mesma network do compose."""
        name = f"worker-{int(time.time())}"
        logger.info("Spawning new worker: %s", name)
        return self.client.containers.run(
            WORKER_IMAGE,
            name=name,
            detach=True,
            labels={"role": "worker"},
            network=WORKER_NETWORK,
            ports={"8001/tcp": None},  # porta dinâmica no host
        )

    def _terminate_worker(self, worker: WorkerInfo) -> None:
        logger.info("Terminating worker: %s", worker.name)
        try:
            c = self.client.containers.get(worker.container_id)
            c.stop(timeout=10)
            c.remove()
        except docker.errors.NotFound:
            pass

    # ---------- Decision Engine ----------

    def decide_and_act(self) -> str:
        metrics = self.collect_metrics()
        if not metrics:
            # nenhuma instância — garantir o mínimo
            if MIN_WORKERS > 0:
                self._spawn_worker()
                self.last_scale_action = time.time()
                return "bootstrapped"
            return "no_workers"

        avg_cpu = sum(w.cpu_percent for w in metrics) / len(metrics)
        in_cooldown = (time.time() - self.last_scale_action) < COOLDOWN_SECONDS

        logger.info("AvgCPU=%.1f%% workers=%d cooldown=%s",
                    avg_cpu, len(metrics), in_cooldown)

        if in_cooldown:
            return "cooldown"

        # Scale up
        if avg_cpu > SCALE_UP_THRESHOLD and len(metrics) < MAX_WORKERS:
            self._spawn_worker()
            self.last_scale_action = time.time()
            return "scaled_up"

        # Scale down (matar o worker menos carregado)
        if avg_cpu < SCALE_DOWN_THRESHOLD and len(metrics) > MIN_WORKERS:
            victim = min(metrics, key=lambda w: w.cpu_percent)
            self._terminate_worker(victim)
            self.last_scale_action = time.time()
            return "scaled_down"

        return "stable"

    # ---------- Load-aware scheduler ----------

    def pick_worker(self) -> WorkerInfo | None:
        """Substitui o FIFO: escolhe o worker com menor CPU%."""
        if not self.workers:
            self.collect_metrics()
        if not self.workers:
            return None
        return min(self.workers.values(), key=lambda w: w.cpu_percent)

    def pick_worker_consolidation(self) -> WorkerInfo | None:
        """
        Variante 'energy-aware': escolhe o worker MAIS carregado
        que ainda tenha folga (<80%). Empacota tarefas em poucos
        workers em vez de espalhar — permite suspender os restantes.
        """
        candidates = [w for w in self.workers.values() if w.cpu_percent < 80]
        if not candidates:
            return None
        return max(candidates, key=lambda w: w.cpu_percent)

    # ---------- Loop ----------

    async def run_forever(self):
        self._running = True
        logger.info("ElasticityEngine started (interval=%ds)", CHECK_INTERVAL)
        while self._running:
            try:
                # run_in_executor keeps blocking Docker SDK calls off the event loop
                await asyncio.get_event_loop().run_in_executor(None, self.decide_and_act)
            except Exception:
                logger.exception("Elasticity tick failed")
            await asyncio.sleep(CHECK_INTERVAL)

    def stop(self):
        self._running = False


engine = ElasticityEngine()