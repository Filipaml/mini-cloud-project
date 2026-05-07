from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from passlib.context import CryptContext
import jwt
import datetime
import httpx  # Necessário para o Mestre falar com o Worker via HTTP

app = FastAPI(title="My Own Cloud - Master Node (Cérebro)")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = "super-secret-key"

# Base de dados temporária (Semana 1)
users_db = {}

# --- Modelos da Semana 1 (Identidade) ---
class User(BaseModel):
    username: str
    password: str

# --- Modelos da Semana 2 (Compute) ---
class JobRequest(BaseModel):
    command: str

# --- Endpoints da Semana 1 ---
@app.post("/register")
def register(user: User):
    if user.username in users_db:
        raise HTTPException(status_code=400, detail="User already exists")
    hashed_pw = pwd_context.hash(user.password)
    users_db[user.username] = {"username": user.username, "password": hashed_pw}
    return {"message": "User registered successfully"}

@app.post("/login")
def login(user: User):
    db_user = users_db.get(user.username)
    if not db_user or not pwd_context.verify(user.password, db_user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = jwt.encode({"sub": user.username, "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1)}, SECRET_KEY)
    return {"access_token": token, "token_type": "bearer"}

# --- NOVO: Endpoints da Semana 2 (Job Submission & FIFO) ---

@app.post("/submit-job")
async def submit_job(job: JobRequest):
    """
    Sistema de Submissão: Recebe a tarefa e envia para o Worker (FIFO simples).
    """
    # URL do nosso Worker dentro da rede Docker
    worker_url = "http://worker-1:8001/execute"
    
    try:
        # O Mestre atua como cliente e envia o pedido para o Worker
        async with httpx.AsyncClient() as client:
            response = await client.post(worker_url, json={"command": job.command}, timeout=70.0)
            
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail="Erro ao comunicar com o Worker Node.")
            
        return response.json() # Devolve o resultado (stdout/stderr) ao utilizador

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro no agendador: {str(e)}")
