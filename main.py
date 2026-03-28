"""
PYFIX License Server — Servidor de licencias SaaS
Desplegado en Railway (PostgreSQL incluido)
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import Base, engine
from routers import auth, licenses, admin

# ── Crear tablas al iniciar ───────────────────────────────────
Base.metadata.create_all(bind=engine)

# ── App ───────────────────────────────────────────────────────
app = FastAPI(
    title="PYFIX License Server",
    description="Servidor de licencias para el sistema POS PYFIX",
    version="1.2.0",
    docs_url="/docs",
    redoc_url=None,
)

# ── CORS (permite peticiones desde la app Electron y web) ────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(licenses.router)
app.include_router(admin.router)


@app.get("/", tags=["health"])
def health():
    return {"status": "ok", "service": "PYFIX License Server", "version": "1.2.0", "endpoints": list(app.routes.__len__())}


@app.get("/health", tags=["health"])
def healthcheck():
    return {"status": "ok"}
