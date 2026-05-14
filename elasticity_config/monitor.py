import httpx
import time
import json

dados = []

print("Monitoring... (Ctrl+C to stop)")
while True:
    try:
        r = httpx.get("http://localhost:8000/metrics",timeout=30.0)
        metrics = r.json()
        snapshot = {
            "time": time.time(),
            "num_workers": len(metrics["workers"]),
            "avg_cpu": sum(w["cpu_percent"] for w in metrics["workers"]) / len(metrics["workers"]) if metrics["workers"] else 0
        }
        dados.append(snapshot)
        print(snapshot)
        time.sleep(2)
    except KeyboardInterrupt:
        break

with open("metrics.json", "w") as f:
    json.dump(dados, f)