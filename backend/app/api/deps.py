from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import PyJWTError
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import get_db
from app.models import AuditLog, Farm, Role, User

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


def current_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    try:
        payload = decode_token(token)
    except PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_token", headers={"WWW-Authenticate": "Bearer"})
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "inactive_user")
    return user


def ministry_user(user: User = Depends(current_user)) -> User:
    if user.role != Role.ministry.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "ministry_only")
    return user


def farmer_user(user: User = Depends(current_user)) -> User:
    if user.role != Role.farmer.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "farmer_only")
    return user


def owned_farm(farm_id: int, db: Session, user: User) -> Farm:
    farm = db.get(Farm, farm_id)
    # ministry may read every farm (national oversight); farmers only their own
    if farm is None or (user.role == Role.farmer.value and farm.owner_id != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "farm_not_found")
    return farm


def audit(db: Session, user: User | None, action: str, target: str = "", payload: dict | None = None) -> None:
    db.add(AuditLog(user_id=user.id if user else None, action=action, target=target, payload=payload or {}))
    db.commit()
