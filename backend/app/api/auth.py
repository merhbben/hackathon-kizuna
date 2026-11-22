import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import audit, current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models import Role, User
from app.schemas import RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])
_failures: dict[str, list[float]] = defaultdict(list)
MAX_FAILURES, WINDOW_S = 5, 900


def _throttled(key: str) -> bool:
    now = time.time()
    _failures[key] = [t for t in _failures[key] if now - t < WINDOW_S]
    return len(_failures[key]) >= MAX_FAILURES


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    """Self-registration is for farmers only. Ministry accounts are created by an administrator (CLI)."""
    email = body.email.lower()
    if db.scalar(select(User).filter_by(email=email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "email_exists")
    user = User(email=email, full_name=body.full_name, password_hash=hash_password(body.password),
                role=Role.farmer.value, governorate_code=body.governorate_code, language=body.language)
    db.add(user)
    db.commit()
    audit(db, user, "register")
    return TokenOut(access_token=create_access_token(str(user.id), user.role), user=UserOut.model_validate(user))


@router.post("/token", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    key = form.username.lower()
    if _throttled(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too_many_attempts")
    user = db.scalar(select(User).filter_by(email=key))
    if not user or not verify_password(form.password, user.password_hash) or not user.is_active:
        _failures[key].append(time.time())
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad_credentials")
    _failures.pop(key, None)
    audit(db, user, "login")
    return TokenOut(access_token=create_access_token(str(user.id), user.role), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


class LangIn(BaseModel):
    language: str


@router.patch("/me", response_model=UserOut)
def set_language(body: LangIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.language not in ("fr", "ar"):
        raise HTTPException(422, "language")
    user.language = body.language
    db.commit()
    return user
