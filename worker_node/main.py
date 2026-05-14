from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import subprocess

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
        # subprocess.run inicia um novo processo no sistema operativo do contentor
        # capture_output=True guarda o que apareceria no terminal (stdout) e os erros (stderr)
        # text=True devolve em formato de string em vez de bytes
        result = subprocess.run(
            job.command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=80 # Protecao: se a tarefa demorar mais de 80s, e cancelada
        )

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