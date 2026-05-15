import subprocess
import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Cloud Worker Node - Compute Engine")

# Modelo do que o Worker espera receber
class JobRequest(BaseModel):
    command: str

# Modelo do que o Worker vai devolver
class JobResponse(BaseModel):
    status: str
    stdout: str
    stderr: str
    return_code: int

@app.post("/execute", response_model=JobResponse)
def execute_job(job: JobRequest):
    try:
        # Executa o comando
        result = subprocess.run(
            job.command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=80
        )

        # --- A MAGIA DA SEMANA 4 ---
        # Criar um nome único para o relatório desta tarefa
        job_id = str(uuid.uuid4())
        caminho_ficheiro = f"/data/storage/resultado_job_{job_id}.txt"
        
        # Guardar o resultado na pasta partilhada (o volume do Docker)
        try:
            with open(caminho_ficheiro, "w") as f:
                f.write(f"--- RELATÓRIO DE TAREFA ---\n")
                f.write(f"ID da Tarefa: {job_id}\n")
                f.write(f"Comando executado: {job.command}\n")
                f.write(f"Status Final: {'Sucesso' if result.returncode == 0 else 'Falha'}\n")
                f.write(f"--- OUTPUT ---\n{result.stdout}\n")
                if result.stderr:
                    f.write(f"--- ERROS ---\n{result.stderr}\n")
        except Exception as e:
            print(f"Aviso: Não foi possível gravar o ficheiro no storage. {e}")
        # ---------------------------

        return JobResponse(
            status="success" if result.returncode == 0 else "failed",
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode
        )

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="Timeout: A tarefa demorou demasiado tempo a executar.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no Worker: {str(e)}")

# Endpoint de stress (Semana 3)
@app.post("/stress")
def stress(seconds: int = 30):
    import time
    t0 = time.time()
    x = 0
    while time.time() - t0 < seconds:
        x += sum(i*i for i in range(10000))
    return {"x": x}