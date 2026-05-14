import json
import sys
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.ticker import MaxNLocator

# --- Configurações reais do elasticity engine ---
SCALE_UP_THRESHOLD = 60    # deve coincidir com elasticity.py / docker-compose
SCALE_DOWN_THRESHOLD = 20  # idem

# --- Carregar dados ---
metrics_file = sys.argv[1] if len(sys.argv) > 1 else "metrics.json"
try:
    with open(metrics_file) as f:
        dados = json.load(f)
except FileNotFoundError:
    print(f"Ficheiro '{metrics_file}' nao encontrado.")
    print("Corre primeiro: python monitor.py")
    sys.exit(1)

if len(dados) < 2:
    print("Dados insuficientes para gerar grafico (precisa de >= 2 amostras).")
    sys.exit(1)

# --- Processar dados ---
t0 = dados[0]["time"]
tempos  = [(d["time"] - t0) for d in dados]
cpu     = [d["avg_cpu"]     for d in dados]
workers = [d["num_workers"] for d in dados]

# Detectar eventos de scaling (mudança no n.º de workers)
scale_up_events   = []
scale_down_events = []
for i in range(1, len(dados)):
    prev_w = dados[i-1]["num_workers"]
    curr_w = dados[i]["num_workers"]
    if curr_w > prev_w:
        scale_up_events.append((tempos[i], cpu[i], curr_w))
    elif curr_w < prev_w:
        scale_down_events.append((tempos[i], cpu[i], curr_w))

# Estatísticas
avg_cpu_total = sum(cpu) / len(cpu)
max_cpu       = max(cpu)
max_workers   = max(workers)
duration      = tempos[-1]
pct_above_up  = sum(1 for c in cpu if c > SCALE_UP_THRESHOLD)  / len(cpu) * 100
pct_below_dn  = sum(1 for c in cpu if c < SCALE_DOWN_THRESHOLD) / len(cpu) * 100

# --- Layout: 2 subplots + painel de texto ---
fig = plt.figure(figsize=(14, 7))
fig.patch.set_facecolor("#0f1117")

# Grelha: 2 linhas, 3 colunas — subplots ocupam colunas 0-1, stats na coluna 2
ax_cpu  = fig.add_subplot(2, 3, (1, 2))   # linha 0, colunas 0-1
ax_wrk  = fig.add_subplot(2, 3, (4, 5), sharex=ax_cpu)  # linha 1, colunas 0-1
ax_stat = fig.add_subplot(1, 3, 3)        # coluna 2, altura toda

for ax in (ax_cpu, ax_wrk, ax_stat):
    ax.set_facecolor("#1a1d27")
    ax.tick_params(colors="#cccccc")
    for spine in ax.spines.values():
        spine.set_edgecolor("#333344")

# ── Subplot 1: CPU % ──────────────────────────────────────────────────────────
ax_cpu.fill_between(tempos, cpu, alpha=0.25, color="#ff6b6b")
ax_cpu.plot(tempos, cpu, color="#ff6b6b", linewidth=1.8, label="CPU médio (%)")

ax_cpu.axhline(SCALE_UP_THRESHOLD,   color="#ffd93d", linestyle="--",
               linewidth=1.2, alpha=0.8, label=f"Scale-up  >{SCALE_UP_THRESHOLD}%")
ax_cpu.axhline(SCALE_DOWN_THRESHOLD, color="#6bcb77", linestyle=":",
               linewidth=1.2, alpha=0.8, label=f"Scale-down <{SCALE_DOWN_THRESHOLD}%")

# Marcar scale-up events no CPU
for t, c, w in scale_up_events:
    ax_cpu.axvline(t, color="#ffd93d", linewidth=1, alpha=0.6)
    ax_cpu.annotate(f"+1 worker\n({w})", xy=(t, c),
                    xytext=(t + duration * 0.01, min(c + 8, 95)),
                    fontsize=7, color="#ffd93d",
                    arrowprops=dict(arrowstyle="->", color="#ffd93d", lw=0.8))

# Marcar scale-down events no CPU
for t, c, w in scale_down_events:
    ax_cpu.axvline(t, color="#6bcb77", linewidth=1, alpha=0.6)
    ax_cpu.annotate(f"-1 worker\n({w})", xy=(t, c),
                    xytext=(t + duration * 0.01, max(c - 15, 5)),
                    fontsize=7, color="#6bcb77",
                    arrowprops=dict(arrowstyle="->", color="#6bcb77", lw=0.8))

ax_cpu.set_ylabel("CPU médio (%)", color="#cccccc", fontsize=10)
ax_cpu.set_ylim(0, 105)
ax_cpu.set_yticks(range(0, int(max(cpu) * 1.1), 100))
ax_cpu.yaxis.label.set_color("#cccccc")
ax_cpu.grid(axis="y", color="#333344", linewidth=0.6)
ax_cpu.legend(loc="upper right", fontsize=8,
              facecolor="#1a1d27", edgecolor="#444455", labelcolor="#cccccc")
ax_cpu.set_title("Elasticity Engine — Cluster State During Stress Test",
                 color="white", fontsize=12, fontweight="bold", pad=10)
plt.setp(ax_cpu.get_xticklabels(), visible=False)

# ── Subplot 2: Workers ────────────────────────────────────────────────────────
ax_wrk.step(tempos, workers, where="post", color="#4ecdc4", linewidth=2,
            label="Workers activos")
ax_wrk.fill_between(tempos, workers, step="post", alpha=0.2, color="#4ecdc4")

# Linhas de min/max
ax_wrk.axhline(1, color="#888899", linestyle=":", linewidth=1, alpha=0.6, label="MIN workers (1)")
ax_wrk.axhline(5, color="#888899", linestyle="--", linewidth=1, alpha=0.6, label="MAX workers (5)")

# Anotações de scaling
for t, _, w in scale_up_events:
    ax_wrk.axvline(t, color="#ffd93d", linewidth=1, alpha=0.5)
for t, _, w in scale_down_events:
    ax_wrk.axvline(t, color="#6bcb77", linewidth=1, alpha=0.5)

ax_wrk.set_xlabel("Tempo (s)", color="#cccccc", fontsize=10)
ax_wrk.set_ylabel("Workers activos", color="#cccccc", fontsize=10)
ax_wrk.set_ylim(0, 6.5)
ax_wrk.yaxis.set_major_locator(MaxNLocator(integer=True))
ax_wrk.grid(axis="y", color="#333344", linewidth=0.6)
ax_wrk.legend(loc="upper right", fontsize=8,
              facecolor="#1a1d27", edgecolor="#444455", labelcolor="#cccccc")
ax_wrk.xaxis.label.set_color("#cccccc")
ax_wrk.yaxis.label.set_color("#cccccc")

# ── Painel de estatísticas ────────────────────────────────────────────────────
ax_stat.axis("off")

def color_for(value, good_max, warn_max):
    if value <= good_max:   return "#6bcb77"
    if value <= warn_max:   return "#ffd93d"
    return "#ff6b6b"

lines = [
    ("RESUMO DO TESTE", None, "white", 13, True),
    ("", None, "white", 8, False),
    (f"Duração:        {duration:.0f}s", None, "#cccccc", 9, False),
    (f"Amostras:       {len(dados)}", None, "#cccccc", 9, False),
    ("", None, "white", 8, False),
    ("── CPU ─────────────────", None, "#555566", 8, False),
    (f"Média:          {avg_cpu_total:.1f}%", None,
     color_for(avg_cpu_total, SCALE_DOWN_THRESHOLD, SCALE_UP_THRESHOLD), 9, False),
    (f"Máximo:         {max_cpu:.1f}%", None,
     color_for(max_cpu, SCALE_DOWN_THRESHOLD, SCALE_UP_THRESHOLD), 9, False),
    (f"Tempo >{SCALE_UP_THRESHOLD}%:  {pct_above_up:.1f}% do teste", None,
     "#ffd93d" if pct_above_up > 0 else "#6bcb77", 9, False),
    (f"Tempo <{SCALE_DOWN_THRESHOLD}%:  {pct_below_dn:.1f}% do teste", None,
     "#6bcb77" if pct_below_dn > 50 else "#cccccc", 9, False),
    ("", None, "white", 8, False),
    ("── SCALING ─────────────", None, "#555566", 8, False),
    (f"Scale-up events:   {len(scale_up_events)}", None,
     "#ffd93d" if scale_up_events else "#cccccc", 9, False),
    (f"Scale-down events: {len(scale_down_events)}", None,
     "#6bcb77" if scale_down_events else "#cccccc", 9, False),
    (f"Workers máximo:    {max_workers}", None, "#4ecdc4", 9, False),
    (f"Workers final:     {workers[-1]}", None, "#4ecdc4", 9, False),
    ("", None, "white", 8, False),
    ("── DIAGNÓSTICO ─────────", None, "#555566", 8, False),
]

# Diagnóstico automático
if pct_above_up == 0 and max_cpu < 10:
    diag = ("CPU sempre perto de 0%.\nStress test pode nao\nter gerado carga.", "#ff6b6b")
elif not scale_up_events and pct_above_up > 20:
    diag = (f"CPU acima de {SCALE_UP_THRESHOLD}% mas\nsem scale-up.\nVerifica cooldown.", "#ffd93d")
elif scale_up_events and max_workers >= 3:
    diag = (f"Scaling funcionou!\n{len(scale_up_events)} scale-up(s)\nobservado(s).", "#6bcb77")
elif scale_up_events:
    diag = (f"Scale-up detectado\nmas modesto\n({max_workers} workers max).", "#ffd93d")
else:
    diag = ("Sistema estavel\nsem necessidade\nde escalar.", "#6bcb77")

lines.append((diag[0], None, diag[1], 9, False))

y = 0.98
for text, _, color, size, bold in lines:
    ax_stat.text(0.05, y, text, transform=ax_stat.transAxes,
                 fontsize=size, color=color,
                 fontweight="bold" if bold else "normal",
                 verticalalignment="top", fontfamily="monospace")
    y -= 0.055 if size >= 9 else 0.03

# Legenda de cores
y -= 0.04
for label, color in [("Scale-up", "#ffd93d"), ("Scale-down", "#6bcb77")]:
    patch = mpatches.Patch(color=color, alpha=0.7)
    ax_stat.text(0.05, y, f"  {label}", transform=ax_stat.transAxes,
                 fontsize=8, color=color, verticalalignment="top")
    y -= 0.05

# --- Guardar e mostrar ---
plt.tight_layout(rect=[0, 0, 1, 1])
out_file = "elasticity_graph.png"
plt.savefig(out_file, dpi=150, facecolor=fig.get_facecolor())
print(f"Grafico guardado em: {out_file}")
plt.show()
