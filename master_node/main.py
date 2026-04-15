from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from passlib.context import CryptContext
import jwt
import datetime

app = FastAPI(title="My Own Cloud - Identity Layer")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = "super-secret-key"

# Base de dados temporária em memória para a Semana 1
users_db = {}

class User(BaseModel):
    username: str
    password: str

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