from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.routers import registration, admin

app = FastAPI(title="HP Registration API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(registration.router)
app.include_router(admin.router)


@app.get("/health")
def health():
    return {"status": "ok"}
