from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from passlib.context import CryptContext
import jwt
import datetime
import httpx
from contextlib import asynccontextmanager
import asyncio
from elasticity import engine, MIN_WORKERS, MAX_WORKERS, SCALE_UP_THRESHOLD

# --- Elasticity Engine (Autoscaler) - Semana 3 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(engine.run_forever())
    yield
    engine.stop()
    task.cancel()

app = FastAPI(title="My Own Cloud - Master Node (Cérebro)", lifespan=lifespan)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = "super-secret-key"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")

# Base de dados temporária (Semana 1)
users_db = {}

def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload["sub"]
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

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

# --- Endpoints da Semana 2 (Job Submission) ---

@app.post("/submit-job")
async def submit_job(job: JobRequest, user=Depends(get_current_user)):
    target = engine.pick_worker_consolidation()
    if not target:
        raise HTTPException(status_code=503, detail="No workers available")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"http://{target.address}/execute",
                json={"command": job.command},
                timeout=90.0,
            )
        return response.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail=f"Worker {target.name} is unreachable")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail=f"Worker {target.name} timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error communicating with worker: {e}")

# --- Endpoints da Semana 3 (Monitorization) ---
@app.get("/metrics")
def get_metrics():
    return {
        "workers": [w.__dict__ for w in engine.workers.values()],
        "min": MIN_WORKERS,
        "max": MAX_WORKERS,
        "scale_up_threshold": SCALE_UP_THRESHOLD,
    }

@app.post("/scale/manual")
def manual_scale(action: str):
    if action == "up":
        engine._spawn_worker()
    elif action == "down" and engine.workers:
        engine._terminate_worker(next(iter(engine.workers.values())))
    return {"workers_now": len(engine.workers)}

