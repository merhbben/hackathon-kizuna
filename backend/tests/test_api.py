from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.main import app
from app.models import User
from tests.test_optimization import FIELD

c = TestClient(app)


def _farmer():
    r = c.post("/api/auth/register", json={"email": "f@test.tn", "full_name": "Farmer", "password": "password1",
                                           "governorate_code": "TN-41"})
    if r.status_code == 409:
        r = c.post("/api/auth/token", data={"username": "f@test.tn", "password": "password1"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _ministry(db):
    if not db.query(User).filter_by(email="m@test.tn").first():
        db.add(User(email="m@test.tn", full_name="M", role="ministry", password_hash=hash_password("password1")))
        db.commit()
    r = c.post("/api/auth/token", data={"username": "m@test.tn", "password": "password1"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_auth_and_roles(db):
    H = _farmer()
    assert c.get("/api/auth/me", headers=H).json()["role"] == "farmer"
    assert c.get("/api/ministry/overview", headers=H).status_code == 403
    assert c.get("/api/farms").status_code == 401
    assert c.post("/api/auth/token", data={"username": "f@test.tn", "password": "wrong-pass"}).status_code == 401
    M = _ministry(db)
    assert c.post("/api/farms", json={"name": "x", "governorate_code": "TN-41"}, headers=M).status_code == 403


def test_full_farm_flow_and_replan(db):
    H = _farmer()
    f = c.post("/api/farms", json={"name": "Ferme", "governorate_code": "TN-41", "declared_area_ha": 8.2,
                                   "soil": {"texture": "sandy_loam"}, "season": "spring_summer"}, headers=H).json()
    fid = f["id"]
    assert c.post(f"/api/farms/{fid}/plans", headers=H).status_code == 422           # no boundary yet
    r = c.put(f"/api/farms/{fid}/boundary", json={"boundary": FIELD, "confirm_area": True}, headers=H).json()
    assert r["area_check"]["ok"] and r["farm"]["area_validated"]
    c.post(f"/api/farms/{fid}/water-sources", json={"kind": "borehole", "latitude": 35.669, "longitude": 10.0801,
                                                    "flow_m3h": 25, "pumping_depth_m": 40}, headers=H)
    r = c.post(f"/api/farms/{fid}/plans", headers=H)
    assert r.status_code == 201, r.text
    plan = r.json()
    assert plan["parcels"] and plan["summary"]["optimizer"]["status"] in ("optimal", "feasible")
    for p in plan["parcels"]:
        m = p["metrics"]
        assert m["production_kg"] > 0 and m["water_m3_season"] >= 0 and m["planting"] < m["harvest"]
    assert plan["energy"]["simulation"]["export"]["hypothesis_note"] == "hypothesis_not_authorised"
    # farmer edits one parcel -> locked with the new crop, AgroBrain recomputes the rest
    target = plan["parcels"][0]
    new_crop = "onion" if target["crop"] != "onion" else "pepper"
    r = c.post(f"/api/farms/{fid}/plans/{plan['id']}/replan",
               json={"edits": [{"parcel_id": target["id"], "crop_code": new_crop}]}, headers=H)
    assert r.status_code == 201, r.text
    p2 = r.json()
    assert p2["version"] == plan["version"] + 1
    assert any(p["locked"] and p["crop"] == new_crop for p in p2["parcels"])
    other = c.post("/api/auth/register", json={"email": "o@test.tn", "full_name": "Other", "password": "password1"})
    OH = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert c.get(f"/api/farms/{fid}", headers=OH).status_code == 404          # isolation between farmers
    M = _ministry(db)
    assert c.get("/api/ministry/overview", headers=M).json()["platform"]      # shared national view


def test_manual_import_requires_source(db):
    M = _ministry(db)
    csv = ("indicator,entity,item,period,value,unit,quality,source_url\n"
           "dam_capacity_mm3,TN-31,Sidi Salem,2025,555,Mm3,official,\n")
    r = c.post("/api/ministry/data-import", files={"file": ("d.csv", csv, "text/csv")}, headers=M).json()
    assert r["imported"] == 0 and r["errors"][0]["error"] == "source_url_required"


def test_policy_update_and_validation(db):
    M = _ministry(db)
    r = c.put("/api/ministry/policy/planning.safety_margin_pct", json={"value": 7, "validate": True}, headers=M)
    row = next(x for x in r.json() if x["key"] == "planning.safety_margin_pct")
    assert row["value"] == 7 and row["status"] == "validated"
    assert c.put("/api/ministry/policy/unknown.key", json={"value": 1}, headers=M).status_code == 404
