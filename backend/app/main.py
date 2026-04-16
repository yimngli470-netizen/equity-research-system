from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.analysis import router as analysis_router
from app.api.decision import router as decision_router
from app.api.ingestion import router as ingestion_router
from app.api.scoring import router as scoring_router
from app.api.stocks import router as stocks_router
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown


app = FastAPI(
    title="AI Equity Research System",
    description="AI-Augmented Equity Research — multi-agent analysis, quant scoring, and decision engine",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stocks_router)
app.include_router(ingestion_router)
app.include_router(analysis_router)
app.include_router(scoring_router)
app.include_router(decision_router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "env": settings.env}
