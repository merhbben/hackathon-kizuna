"""Administration CLI.

  python -m app.cli bootstrap            # load real data: FAOSTAT, World Bank, NASA POWER (24 governorates), train models
  python -m app.cli create-user --email x@y.tn --name "..." --role ministry
  python -m app.cli alerts               # recompute alerts
"""
from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from app.connectors import sources
from app.connectors.base import ConnectorError, mark_status
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.engines import forecast, national
from app.models import Role, User


def bootstrap() -> None:
    db = SessionLocal()
    print("FAOSTAT (cached Tunisia extract) ...", sources.load_faostat(db), "records")
    try:
        print("World Bank population ...", sources.fetch_population(db), "records")
    except ConnectorError as e:
        mark_status(db, "worldbank", False, message=str(e))
        print("  ! World Bank unavailable:", e, "-> FAOSTAT population used as fallback")
    clims = national.governorate_climates(db, fetch=True)
    print("NASA POWER climatology:", len(clims), "/ 24 governorates")
    for task in ("demand_per_capita", "yield"):
        r = forecast.train_and_select(db, task)
        print(f"Model selection [{task}] years {r.get('years')}:")
        for crop, v in r["crops"].items():
            print(f"  {crop:12s} -> {v['selected']:13s} MAPE {v['mape_pct']:6.2f} %  {v['comparison']}")
    national.refresh_alerts(db, with_rain=False)
    print("Done.")


def create_user(email: str, name: str, role: str, governorate: str | None) -> None:
    db = SessionLocal()
    if db.scalar(select(User).filter_by(email=email.lower())):
        sys.exit("user exists")
    pw = getpass.getpass("Password (min 8 chars): ")
    if len(pw) < 8:
        sys.exit("password too short")
    db.add(User(email=email.lower(), full_name=name, role=Role(role).value, governorate_code=governorate,
                password_hash=hash_password(pw)))
    db.commit()
    print("created", email, role)


def main() -> None:
    p = argparse.ArgumentParser(prog="agrosphere")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("bootstrap")
    sub.add_parser("alerts")
    cu = sub.add_parser("create-user")
    cu.add_argument("--email", required=True)
    cu.add_argument("--name", required=True)
    cu.add_argument("--role", choices=[r.value for r in Role], required=True)
    cu.add_argument("--governorate")
    a = p.parse_args()
    if a.cmd == "bootstrap":
        bootstrap()
    elif a.cmd == "alerts":
        national.refresh_alerts(SessionLocal())
    else:
        create_user(a.email, a.name, a.role, a.governorate)


if __name__ == "__main__":
    main()
