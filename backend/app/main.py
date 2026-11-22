import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, farms, inputs, ministry, plan_import, reference
from app.core.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()

app = FastAPI(title=settings.app_name, version="1.0.0",
              description="AgroSphere AI — planification agricole nationale et plans de ferme optimisés (Tunisie)")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return resp


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):  # never leak stack traces to clients
    logging.getLogger("agrosphere").exception("Unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "internal_error"}, status_code=500)


for r in (auth.router, plan_import.router, inputs.router, farms.router, ministry.router, reference.router):
    app.include_router(r)


@app.on_event("startup")
def warm_cache() -> None:
    """Pre-compute the national balance in the background so the first dashboard load is fast."""
    import threading

    def _warm():
        from app.db.session import SessionLocal
        from app.engines import national
        db = SessionLocal()
        try:
            national.national_balance(db)
            national.governorate_guidance(db)
        except Exception:  # data not bootstrapped yet: nothing to warm
            logging.getLogger("agrosphere").info("cache warm-up skipped")
        finally:
            db.close()
    if settings.environment != "test":
        threading.Thread(target=_warm, daemon=True).start()


@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.app_name}
