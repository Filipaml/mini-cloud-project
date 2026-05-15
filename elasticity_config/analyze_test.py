"""
Análise detalhada do comportamento do stress test.
Mostra quando deveria ter escalado e porquê não escalou.
"""
import json
import sys

if len(sys.argv) > 1:
    metrics_file = sys.argv[1]
else:
    metrics_file = "metrics.json"

try:
    with open(metrics_file) as f:
        dados = json.load(f)
except FileNotFoundError:
    print(f" Ficheiro '{metrics_file}' não encontrado")
    print("   Corre primeiro: python monitor.py (enquanto o stress test corre)")
    sys.exit(1)

# Configurações (mesmas que no elasticity.py / docker-compose.yml)
SCALE_UP_THRESHOLD = 60
SCALE_DOWN_THRESHOLD = 20
COOLDOWN_SECONDS = 30
CHECK_INTERVAL = 10

print("="*70)
print("ANÁLISE DO STRESS TEST")
print("="*70)

t0 = dados[0]["time"]
print(f"\nDuração total: {dados[-1]['time'] - t0:.1f}s")
print(f"Samples: {len(dados)}")

print("\n" + "="*70)
print("EVENTOS DE SCALING")
print("="*70)

last_workers = dados[0]["num_workers"]
last_scale_time = 0

for i, d in enumerate(dados):
    t = d["time"] - t0
    cpu = d["avg_cpu"]
    workers = d["num_workers"]
    
    # Detectar mudanças no número de workers
    if workers != last_workers:
        cooldown_remaining = max(0, COOLDOWN_SECONDS - (t - last_scale_time))
        print(f"\n t={t:5.1f}s: SCALING {last_workers} → {workers} workers")
        print(f"   CPU médio antes: {dados[i-1]['avg_cpu']:.1f}%")
        print(f"   CPU médio depois: {cpu:.1f}%")
        last_workers = workers
        last_scale_time = t

# Analisar oportunidades perdidas de scaling
print("\n" + "="*70)
print("OPORTUNIDADES PERDIDAS DE SCALE-UP")
print("="*70)

missed_opportunities = []
in_cooldown_at = []

for i, d in enumerate(dados):
    t = d["time"] - t0
    cpu = d["avg_cpu"]
    workers = d["num_workers"]
    
    # Calcular se está em cooldown
    time_since_last_scale = t - last_scale_time if i > 0 else t
    in_cooldown = time_since_last_scale < COOLDOWN_SECONDS
    
    # Deveria escalar mas não escalou?
    should_scale = cpu > SCALE_UP_THRESHOLD and workers < 5
    
    if should_scale:
        if in_cooldown:
            in_cooldown_at.append((t, cpu, workers))
        else:
            missed_opportunities.append((t, cpu, workers))

if in_cooldown_at:
    print(f"\n BLOQUEADO POR COOLDOWN ({len(in_cooldown_at)} momentos):")
    for t, cpu, workers in in_cooldown_at[:5]:  # mostrar primeiros 5
        print(f"   t={t:5.1f}s: CPU={cpu:5.1f}% (workers={workers}) — QUERIA escalar mas em cooldown")
    if len(in_cooldown_at) > 5:
        print(f"   ... e mais {len(in_cooldown_at)-5} momentos")

if missed_opportunities:
    print(f"\n❓ OPORTUNIDADES NÃO APROVEITADAS ({len(missed_opportunities)} momentos):")
    for t, cpu, workers in missed_opportunities[:5]:
        print(f"   t={t:5.1f}s: CPU={cpu:5.1f}% (workers={workers}) — PODIA ter escalado!")

# Estatísticas finais
print("\n" + "="*70)
print("ESTATÍSTICAS")
print("="*70)

avg_cpu = sum(d["avg_cpu"] for d in dados) / len(dados)
max_cpu = max(d["avg_cpu"] for d in dados)
max_workers = max(d["num_workers"] for d in dados)

# Tempo acima do threshold
time_above_threshold = sum(1 for d in dados if d["avg_cpu"] > SCALE_UP_THRESHOLD)
pct_above = (time_above_threshold / len(dados)) * 100

print(f"\nCPU médio geral: {avg_cpu:.1f}%")
print(f"CPU máximo: {max_cpu:.1f}%")
print(f"Workers máximo: {max_workers}")
print(f"Tempo acima de {SCALE_UP_THRESHOLD}%: {pct_above:.1f}% do teste")

# Diagnóstico
print("\n" + "="*70)
print("DIAGNÓSTICO")
print("="*70)

if pct_above > 50 and max_workers < 5:
    print("\n  PROBLEMA: CPU alto durante muito tempo mas não escalou até ao máximo")
    print("    Possíveis causas:")
    print("    1. Cooldown demasiado longo (60s) — considera reduzir para 30s")
    print("    2. Check interval demasiado espaçado (15s) — considera 10s")
    print("    3. Carga do stress test demasiado intensa para o sistema escalar")
elif max_workers == 5:
    print("\n Escalou até ao máximo (5 workers)")
    if avg_cpu > SCALE_UP_THRESHOLD:
        print("    Mas CPU ainda está alto — precisas de MAX_WORKERS maior ou menos carga")
else:
    print("\n Sistema comportou-se de forma razoável")

print("\n" + "="*70)
