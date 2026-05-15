import asyncio
import datetime
import logging
from contextlib import asynccontextmanager

import httpx
import jwt
import docker  
from fastapi import FastAPI, HTTPException, Depends, Form
from fastapi.security import OAuth2PasswordRequestForm
from passlib.context import CryptContext
from pydantic import BaseModel

from auth import SECRET_KEY, get_current_user
from db import init_db
from elasticity import engine, MIN_WORKERS, MAX_WORKERS, SCALE_UP_THRESHOLD
from storage import router as storage_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# --- (Container Service) ---
class ContainerDeploy(BaseModel):
    image: str  
    name: str   # Name the user wants to assign to the container

# --- Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(engine.run_forever())
    try:
        yield
    finally:
        engine.stop()
        task.cancel()

app = FastAPI(title="My Own Cloud - Master Node", lifespan=lifespan)
app.include_router(storage_router)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
users_db: dict[str, dict] = {}
docker_client = docker.from_env() # Connect to Host's Docker Engine

# --- Week 1 (Identity) ---
class User(BaseModel):
    username: str
    password: str

@app.post("/register", response_model=dict)
def register(user: User):
    if user.username in users_db:
        raise HTTPException(status_code=400, detail="User already exists")
    hashed_pw = pwd_context.hash(user.password)
    users_db[user.username] = {"username": user.username, "password": hashed_pw}
    return {"message": "User registered successfully"}

@app.post("/login", response_model=dict)
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    db_user = users_db.get(form_data.username)
    if not db_user or not pwd_context.verify(form_data.password, db_user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = jwt.encode({"sub": form_data.username, "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1)}, SECRET_KEY)
    return {"access_token": token, "token_type": "bearer"}

# --- Week 2 (Job Submission) ---
class JobRequest(BaseModel):
    command: str

@app.post("/submit-job", response_model=dict)
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error communicating with worker: {e}")

# --- Week 3 (Monitorization) ---
@app.get("/metrics", response_model=dict)
def get_metrics():
    return {
        "workers": [w.__dict__ for w in engine.workers.values()],
        "min": MIN_WORKERS,
        "max": MAX_WORKERS,
    }

# --- Week 5: CONTAINER SERVICE (CaaS) ---

@app.post("/containers/deploy", response_model=dict)
def deploy_container(req: ContainerDeploy, user=Depends(get_current_user)):
    """Deploys a new isolated container instance upon user request."""
    try:
        # Master Node acting as the Orchestrator
        container = docker_client.containers.run(
            req.image,
            name=f"user-{user}-{req.name}", # Isolated naming convention per user
            detach=True,
            labels={"owner": user}
        )
        return {"status": "deployed", "container_id": container.short_id, "name": container.name}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to deploy container: {e}")

@app.get("/containers/list", response_model=list[dict])
def list_user_containers(user=Depends(get_current_user)):
    """Lists all active containers owned by the authenticated user."""
    containers = docker_client.containers.list(all=True, filters={"label": f"owner={user}"})
    return [{"id": c.short_id, "name": c.name, "status": c.status, "image": c.image.tags} for c in containers]

@app.delete("/containers/{container_name}", response_model=dict)
def stop_container(container_name: str, user=Depends(get_current_user)):
    """Stops and completely removes a specified user container."""
    try:
        # Ensure the user can only delete their own containers (Security/Multi-tenancy)
        container = docker_client.containers.get(container_name)
        if container.labels.get("owner") != user:
            raise HTTPException(status_code=403, detail="You do not have permission to delete this container")
        
        container.stop()
        container.remove()
        return {"message": f"Container {container_name} removed successfully"}
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Container not found or error occurred: {e}")