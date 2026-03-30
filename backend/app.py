from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from routers.users import router
from routers.document_process import router as document_router
from routers.chat import router as chat_router
from database import init_db
from config import ALLOWED_ORIGINS

# Initialize database before app startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database
    init_db()
    print("✓ Application started successfully")
    yield
    # Shutdown: Cleanup if needed
    print("✓ Application shutdown")

app = FastAPI(
    title="AI PDF Bot Backend",
    version="1.0.0",
    description="AI PDF Bot - Backend API with SQLite/Cloud SQL support",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api", tags=["users"])
app.include_router(document_router, prefix="/api", tags=["documents"])
app.include_router(chat_router, prefix="/api", tags=["chat"])

@app.get("/")
def read_root():
    return {
        "message": "Welcome to AI PDF Bot Backend",
        "version": "1.0.0",
        "docs": "/docs"
    }

@app.get("/health")
def health_check():
    return {"status": "healthy"}
