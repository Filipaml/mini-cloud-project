"""
Stress test melhorado com diferentes perfis de carga:
- gradual: aumenta carga progressivamente (bom para ver scaling)
- burst: rajadas intensas com pausas (testa resposta rápida)
- sustained: carga constante moderada (testa estabilidade)

Uso:
    python stress_test_v2.py gradual
    python stress_test_v2.py burst
    python stress_test_v2.py sustained
"""

import concurrent.futures
import json
import sys
import time
import urllib.error
import urllib.request

MASTER_URL = "http://localhost:8000"
USERNAME = "stress_user"
PASSWORD = "stress_pass123"


def post_json(url, data, token=None):
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def get_json(url, token=None):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def register_and_login():
    import urllib.parse  # para formatar o formulário
    
    # 1. Registo (Continua igual, este funciona como JSON)
    try:
        post_json(f"{MASTER_URL}/register", {"username": USERNAME, "password": PASSWORD})
        print("    Utilizador registado")
    except urllib.error.HTTPError as e:
        if e.code == 400:
            print("    A usar conta existente")
        else:
            raise

    # 2. Login (A grande mudança está aqui!)
    print("   [2/2] A obter token de acesso...")
    
    # Em vez de JSON, enviamos dados de formulário (URL Encoded)
    login_data = urllib.parse.urlencode({
        "username": USERNAME, 
        "password": PASSWORD
    }).encode('utf-8')
    
    # Criamos o pedido para o endpoint /token (que é o padrão do Master)
    req = urllib.request.Request(
        f"{MASTER_URL}/login", 
        data=login_data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        return data["access_token"]


def send_stress_job(token, duration):
    """Envia um job que consome CPU durante 'duration' segundos"""
    # IMPORTANTE: python3 -c não aceita 'while ...: body; next_stmt' numa linha —
    # o interpretador requer newline real para separar blocos.
    # Solução robusta: codificar o script em base64 e descodificar no worker.
    # Assim evitamos todos os problemas de escaping de aspas e newlines na shell.
    import base64
    script = (
        f"import time\n"
        f"t=time.time()\n"
        f"x=0\n"
        f"while time.time()-t<{duration}:\n"
        f"    x+=sum(i*i for i in range(10000))\n"
        f"print('CPU stress: ' + str(x) + ' iters')\n"
    )
    b64 = base64.b64encode(script.encode()).decode()
    cmd = f"python3 -c \"import base64; exec(base64.b64decode('{b64}').decode())\""
    try:
        resp = post_json(f"{MASTER_URL}/submit-job", {"command": cmd}, token=token)
        status = resp.get("status", "unknown")
        # Debug: se falhar, mostra stderr
        if status != "success":
            stderr = resp.get("stderr", "")
            stdout = resp.get("stdout", "")
            rc = resp.get("return_code", "?")
            return f"failed(rc={rc}): {stderr[:50] if stderr else stdout[:50] or 'no output'}"
        return status
    except Exception as e:
        return f"erro: {str(e)[:50]}"


def print_metrics(token):
    try:
        m = get_json(f"{MASTER_URL}/metrics", token=token)
        workers = m.get('workers', [])
        print(f"  Workers: {len(workers)}  (min={m.get('min', '?')} max={m.get('max', '?')})")
        if workers:
            avg_cpu = sum(w['cpu_percent'] for w in workers) / len(workers)
            print(f"  CPU médio: {avg_cpu:.1f}%  (threshold={m.get('scale_up_threshold', '?')}%)")
    except Exception as e:
        print(f"   Erro ao obter métricas: {e}")


def test_gradual(token):
    """
    Aumenta carga gradualmente: 3 waves com mais pedidos em cada.
    Permite ver o scaling acontecer em múltiplas etapas.
    """
    print("\n=== MODO: GRADUAL (3 waves) ===")
    print("Wave 1: 5 pedidos × 20s (carga leve)")
    print("Wave 2: 10 pedidos × 20s (carga média)")
    print("Wave 3: 20 pedidos × 20s (carga alta)")
    print("\nAguarda 30s entre waves para ver o sistema reagir\n")
    
    waves = [
        (5, 20, "leve"),
        (10, 20, "média"),
        (20, 20, "alta")
    ]
    
    for wave_num, (num_requests, duration, label) in enumerate(waves, 1):
        print(f"\n--- Wave {wave_num}/3: {num_requests} pedidos ({label}) ---")
        print_metrics(token)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_requests) as pool:
            futures = [pool.submit(send_stress_job, token, duration) for _ in range(num_requests)]
            results = {"success": 0, "failed": 0, "erro": 0}
            for fut in concurrent.futures.as_completed(futures):
                status = fut.result()
                if status == "success":
                    results["success"] += 1
                elif status.startswith("failed"):
                    results["failed"] += 1
                    # Mostra o primeiro erro para debug
                    if results["failed"] == 1:
                        print(f"\n  ⚠ Primeiro failure: {status}")
                else:
                    results["erro"] += 1
                done = sum(results.values())
                print(f"  [{done:2d}/{num_requests}] {status[:20]}", end="\r", flush=True)
            print()  # newline após o loop
        
        print(f"✓ Wave {wave_num} concluída: {results['success']} ok, {results['failed']} failed, {results['erro']} erros")
        
        if wave_num < len(waves):
            print("\n  Aguardar 30s para ver reação do sistema...")
            time.sleep(30)


def test_burst(token):
    """
    Rajadas intensas com pausas: 3 bursts de 15 pedidos × 15s.
    Testa se o sistema responde rapidamente a picos.
    """
    print("\n=== MODO: BURST (3 bursts) ===")
    print("Burst 1, 2, 3: 15 pedidos × 15s cada")
    print("Pausa de 45s entre bursts\n")
    
    for burst_num in range(1, 4):
        print(f"\n--- Burst {burst_num}/3 ---")
        print_metrics(token)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as pool:
            futures = [pool.submit(send_stress_job, token, 15) for _ in range(15)]
            results = {"success": 0, "failed": 0, "erro": 0}
            for fut in concurrent.futures.as_completed(futures):
                status = fut.result()
                if status == "success":
                    results["success"] += 1
                elif status.startswith("failed"):
                    results["failed"] += 1
                else:
                    results["erro"] += 1
                done = sum(results.values())
                print(f"  [{done:2d}/15] {status[:20]}", end="\r", flush=True)
            print()
        
        print(f"✓ Burst {burst_num} concluído: {results['success']} ok, {results['failed']} failed, {results['erro']} erros")
        
        if burst_num < 3:
            print("\n  Pausa de 45s...")
            time.sleep(45)


def test_sustained(token):
    """
    Carga constante: 12 pedidos × 60s.
    Testa se o sistema mantém estabilidade sob carga moderada contínua.
    """
    print("\n=== MODO: SUSTAINED ===")
    print("12 pedidos × 60s (carga constante moderada)\n")
    
    print_metrics(token)
    
    print("\nA enviar 12 pedidos de 60s...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(send_stress_job, token, 60) for _ in range(12)]
        results = {"success": 0, "failed": 0, "erro": 0}
        for fut in concurrent.futures.as_completed(futures):
            status = fut.result()
            if status == "success":
                results["success"] += 1
            elif status.startswith("failed"):
                results["failed"] += 1
            else:
                results["erro"] += 1
            done = sum(results.values())
            print(f"  [{done:2d}/12] {status[:20]}", flush=True)
    
    print(f"\n Teste concluído: {results['success']} ok, {results['failed']} failed, {results['erro']} erros")


def main():
    if len(sys.argv) < 2:
        print("Uso: python stress_test.py [gradual|burst|sustained]")
        print("\ngradual  - aumenta carga em 3 waves (melhor para ver scaling)")
        print("burst    - 3 rajadas intensas com pausas (testa resposta rápida)")
        print("sustained- carga constante moderada (testa estabilidade)")
        sys.exit(1)
    
    mode = sys.argv[1].lower()
    if mode not in ["gradual", "burst", "sustained"]:
        print(f" Modo '{mode}' inválido. Usa: gradual, burst ou sustained")
        sys.exit(1)
    
    print(f"Master: {MASTER_URL}")
    print("\n[1/2] A autenticar...")
    token = register_and_login()
    
    print("\n[2/2] Métricas iniciais:")
    print_metrics(token)
    
    # Escolher teste
    if mode == "gradual":
        test_gradual(token)
    elif mode == "burst":
        test_burst(token)
    else:
        test_sustained(token)
    
    print("\n" + "="*50)
    print("Métricas finais:")
    print_metrics(token)
    print("="*50)
    
    print("\n Corre 'python analyze_test.py' para analisar os resultados")


if __name__ == "__main__":
    main()