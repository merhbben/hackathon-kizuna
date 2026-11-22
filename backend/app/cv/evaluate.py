"""Measure plan-recognition accuracy on the fixture plans and write docs/EVALUATION.md.

    python -m app.cv.evaluate            (from backend/)
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

from shapely.geometry import Polygon

from app.cv.plan_parser import parse

FIX = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "plans"
OUT = Path(__file__).resolve().parents[3] / "docs" / "EVALUATION.md"
PLANS = ["nabeul", "kairouan", "sfax", "gafsa"]
VARIANTS = [(".pdf", "PDF vectoriel"), (".svg", "SVG"), (".png", "PNG couleur 150 dpi"), ("_bw.png", "PNG noir & blanc")]


def evaluate() -> list[dict]:
    rows = []
    for name in PLANS:
        R = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))
        ref_poly = Polygon(R["vector_reference"]["boundary_m"])
        ref_edges = sorted(e["length_m"] for e in R["vector_reference"]["edges"])
        for suffix, label in VARIANTS:
            fn = f"{name}{suffix}"
            t = time.time()
            r = parse((FIX / fn).read_bytes(), fn)
            dt = time.time() - t
            row = {"plan": name, "format": label, "seconds": round(dt, 1), "ok": r["ok"]}
            if r["ok"]:
                got = Polygon(r["boundary_m"])
                edges = sorted(e["length_m"] for e in r["edges"])
                wp_err = []
                for w in R["vector_reference"]["water_points"]:
                    if r["water_points"]:
                        wp_err.append(min(math.dist((w["x_m"], w["y_m"]), (g["x_m"], g["y_m"])) for g in r["water_points"]))
                m = r["metadata"]
                fields = ["water_m3_day", "pump_kw", "solar_kwc", "battery_kwh"]
                row.update(
                    area_err_pct=round(100 * (r["area"]["measured_m2"] - R["printed"]["area_m2"]) / R["printed"]["area_m2"], 2),
                    iou=round(got.intersection(ref_poly).area / got.union(ref_poly).area, 4),
                    vertices=f'{len(r["boundary_m"])}/{len(ref_poly.exterior.coords) - 1}',
                    edge_err_pct=round(max(abs(a - b) / a * 100 for a, b in zip(ref_edges, edges)), 2) if len(edges) == len(ref_edges) else None,
                    water_points=f'{len(r["water_points"])}/{len(R["vector_reference"]["water_points"])}',
                    water_err_m=round(max(wp_err), 2) if wp_err else None,
                    governorate=(m.get("governorate") or {}).get("code") == R["printed"]["governorate"],
                    resources=f'{sum(1 for f in fields if m.get(f) is not None and abs(m[f] - R["printed"][f]) < 1e-6)}/{len(fields)}',
                    scale=r["scale"]["method"],
                )
            rows.append(row)
    return rows


def write(rows: list[dict]) -> None:
    head = ["Plan", "Format", "Surface (écart %)", "IoU contour", "Sommets", "Côté max (écart %)", "Points d'eau",
            "Position eau (m, max)", "Gouvernorat", "Ressources lues", "Échelle", "Temps (s)"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        if not r["ok"]:
            lines.append(f"| {r['plan']} | {r['format']} | ÉCHEC | | | | | | | | | {r['seconds']} |")
            continue
        lines.append(f"| {r['plan']} | {r['format']} | {r['area_err_pct']:+.2f} | {r['iou']:.3f} | {r['vertices']} | "
                     f"{r['edge_err_pct']} | {r['water_points']} | {r['water_err_m']} | {'✓' if r['governorate'] else '✗'} | "
                     f"{r['resources']} | {r['scale']} | {r['seconds']} |")
    ok = [r for r in rows if r["ok"]]
    vec = [r for r in ok if r["format"] in ("PDF vectoriel", "SVG")]
    ras = [r for r in ok if r not in vec]
    summ = (f"- Plans lus : **{len(ok)}/{len(rows)}**\n"
            f"- Vectoriel (PDF/SVG) : écart de surface max **{max(abs(r['area_err_pct']) for r in vec):.2f} %**, "
            f"IoU min **{min(r['iou'] for r in vec):.4f}**, position des points d'eau max **{max(r['water_err_m'] or 0 for r in vec):.2f} m**\n"
            f"- Image (PNG couleur et N&B, OCR) : écart de surface max **{max(abs(r['area_err_pct']) for r in ras):.2f} %**, "
            f"IoU min **{min(r['iou'] for r in ras):.4f}**, côté max **{max(r['edge_err_pct'] or 0 for r in ras):.2f} %**, "
            f"position des points d'eau max **{max(r['water_err_m'] or 0 for r in ras):.2f} m**\n")
    OUT.write_text(f"""# Évaluation de la lecture des plans

Généré par `python -m app.cv.evaluate` (backend). Jeu d'essai : `backend/tests/fixtures/plans`, 4 plans
synthétiques NON OFFICIELS fournis par l'utilisateur (`Atlas_4_plans_agricoles_test.pdf`), déclinés en
PDF, SVG, PNG couleur (150 dpi) et PNG noir & blanc (seuillage d'Otsu).

**Référence** : surface et ressources = valeurs imprimées sur chaque plan ; contour, côtés et points
d'eau = géométrie lue dans les primitives vectorielles du PDF (repère local en mètres). La surface
vectorielle est donc comparée à une valeur indépendante (le texte imprimé) ; les images sont comparées
à la géométrie vectorielle.

## Résumé

{summ}
## Détail

{chr(10).join(lines)}

## Limites connues

- Les plans d'essai ne contiennent **pas de coordonnées GPS** : le terrain est placé au centre du
  gouvernorat (signalé « position approximative »), ce qui rend le climat et le sol approximatifs.
- Les plans n'indiquent pas le **débit des pompes** ni la profondeur des forages : les volumes d'eau sont
  calculés, mais pas les durées d'arrosage ni l'énergie exacte de pompage (minimum seulement).
- Pas de saison ni de sol sur les plans : toutes les saisons sont étudiées et le sol vient de SoilGrids.
- Sur le PNG couleur de Nabeul, la barre d'échelle est recouverte par un chemin : l'échelle est déduite de la
  surface imprimée (signalé), avec un résultat exact.
- Ces mesures portent sur 4 plans de même style graphique. D'autres styles (scans de plans papier, cotes
  manuscrites, plans sans bornes B1…Bn) n'ont pas encore été évalués : un corpus réel annoté est nécessaire.

## Qualité agronomique (évaluée séparément)

Les prévisions (demande par habitant, rendements) sont évaluées par backtest temporel et enregistrées
dans le registre des modèles (Ministère › Alertes et gestion › Données & modèles). Voir `docs/STATUS.md`.
Les recommandations de cultures ne peuvent pas être « notées » sans parcelles réelles et récoltes
observées : leur validation par les CRDA/INRAT reste à faire.
""", encoding="utf-8")


if __name__ == "__main__":
    rows = evaluate()
    write(rows)
    for r in rows:
        print(r)
