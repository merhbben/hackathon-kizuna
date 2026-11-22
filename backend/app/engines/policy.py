"""Ministry policy parameters with defaults, status and provenance.

Defaults are explicitly flagged `draft`: they are starting points for the
ministry, never presented as regulations. Only an authorised ministry user can
change them (status becomes `validated` when they confirm).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PolicySetting

DEFAULTS: dict[str, dict] = {
    "planning.safety_margin_pct": {"value": 5.0, "source": "Paramètre de planification (à fixer par le ministère)"},
    "planning.horizon_year": {"value": date.today().year + 1, "source": "Année cible de planification"},
    "planning.reserve_days": {"value": 30, "source": "Jours de consommation à garder en réserve (proposition)"},
    "planning.imports_planned_kt": {"value": {}, "source": "Vide = moyenne FAOSTAT des 3 dernières années"},
    "planning.exports_planned_kt": {"value": {}, "source": "Vide = moyenne FAOSTAT des 3 dernières années"},
    "planning.price_elasticity": {"value": {}, "source": "Élasticités-prix de la demande (études ONAGRI/INS) — "
                                                       "vide = analyse qualitative seulement"},
    "farms.large_farm_min_ha": {"value": 50.0, "source": "Seuil proposé — à valider par l'autorité compétente"},
    "farms.large_farm_min_boreholes": {"value": 3, "source": "Seuil proposé — à valider"},
    "farms.contribution_cap_pct": {"value": 10.0, "source": "Plafond de contribution aux réserves (proposition)"},
    "energy.reserve_share": {"value": 0.20, "source": "Part de la production PV réservée au stockage de secours"},
    "energy.crisis_min_soc": {"value": 0.50, "source": "Niveau minimal de batterie conservé pour les crises"},
    "energy.autonomy_hours": {"value": 24.0, "source": "Autonomie visée sur charges critiques"},
    "energy.injection_cap_pct": {"value": 0.30, "source": "Décret n°2020-105 modifiant le décret n°2016-1123 "
                                                          "(loi 2015-12 modifiée par loi 2019-47) : vente des "
                                                          "excédents limitée à 30 % de la production annuelle — "
                                                          "à vérifier avec STEG/ANME selon contrat et niveau de "
                                                          "tension"},
    "energy.hypothesis_sale_pct": {"value": 0.80, "source": "Scénario souhaité — hypothèse NON autorisée"},
    "energy.pv_cost_tnd_kwp": {"value": None, "source": "Coût installé PV (devis / ANME) — à renseigner"},
    "energy.battery_cost_tnd_kwh": {"value": None, "source": "Coût batterie — à renseigner"},
    "energy.grid_tariff_tnd_kwh": {"value": None, "source": "Tarif STEG applicable — à renseigner"},
    "energy.export_tariff_tnd_kwh": {"value": None, "source": "Tarif de rachat STEG (décision ministérielle)"},
    "storage.cold_room_cost_tnd_m3": {"value": None, "source": "Coût chambre froide — à renseigner"},
    "storage.cold_building_min_ha": {"value": 65.0, "source": "Au-delà de cette surface, un bâtiment frigorifique "
                                                              "est obligatoire (règle du projet, à valider)"},
    "storage.offseason_min_weeks": {"value": 8, "source": "Durée de conservation minimale pour décaler une "
                                                          "récolte vers la contre-saison (USDA HB66)"},
    "storage.cold_backup_hours": {"value": 6.0, "source": "Heures de secours batterie du bâtiment frigorifique en "
                                                         "cas de coupure (chambre fermée ; proposition)"},
    "storage.offseason_share_pct": {"value": 50.0, "source": "Part de la récolte stockée pour la contre-saison "
                                                             "(proposition, à valider)"},
    "economics.reference_prices_tnd_kg": {"value": {}, "source": "Prix de référence (ONAGRI / marché de gros)"},
    "economics.reference_costs_tnd_ha": {"value": {}, "source": "Coûts de production de référence (CRDA)"},
    # unit prices of the automatic production-cost model (engines/costs.py); quality shown next to each cost
    "costs.smag_tnd_day": {"value": 21.336, "quality": "official",
                           "source": "Décret n° 2026-66 : SMAG 21,336 DT par jour au 1er janvier 2026 "
                                     "(22,400 DT au 1er janvier 2027)"},
    "costs.ammonitrate_tnd_t": {"value": 720.0, "quality": "official",
                                "source": "Prix de détail de l'ammonitrate fixé pour la campagne 2024-2025"},
    "costs.dap_tnd_t": {"value": 690.0, "quality": "estimated",
                        "source": "Dernier prix public relevé du DAP (2021) — à actualiser (GCT / ministère)"},
    "costs.sop_tnd_t": {"value": 1500.0, "quality": "estimated", "source": "Sulfate de potasse — estimation à valider"},
    "costs.cereal_seed_tnd_kg": {"value": 1.4, "quality": "estimated",
                                 "source": "Semence certifiée de céréales — estimation à valider"},
    "costs.legume_seed_tnd_kg": {"value": 4.0, "quality": "estimated",
                                 "source": "Semence de légumineuses — estimation à valider"},
    "costs.potato_seed_tnd_kg": {"value": 3.5, "quality": "estimated",
                                 "source": "Semence de pomme de terre : plus de 3 500 DT/t (FNPPT, 2019)"},
    "costs.vegetable_seed_tnd_kg": {"value": 300.0, "quality": "estimated",
                                    "source": "Semence hybride (oignon, carotte) — estimation à valider"},
    "costs.seedling_tnd_plant": {"value": 0.12, "quality": "estimated",
                                 "source": "Plant de pépinière (tomate, piment, cucurbitacées) — estimation"},
    "costs.offshoot_tnd_plant": {"value": 0.30, "quality": "estimated", "source": "Œilleton d'artichaut — estimation"},
    "costs.tractor_tnd_h": {"value": 45.0, "quality": "estimated",
                            "source": "Heure de tracteur ou de prestation — estimation à valider"},
    "costs.treatment_tnd_ha": {"value": 70.0, "quality": "estimated",
                               "source": "Un traitement phytosanitaire par ha (produit + passage) — estimation"},
    "costs.network_water_tnd_m3": {"value": 0.110, "quality": "official",
                                   "source": "Coût moyen de l'eau d'irrigation : 0,110 DT/m³ (BPEH, Rapport national "
                                             "du secteur de l'eau 2020)"},
    "costs.drip_tnd_ha_year": {"value": 400.0, "quality": "estimated",
                               "source": "Entretien et renouvellement annuel du goutte-à-goutte — estimation"},
    "alerts.rain_anomaly_warning": {"value": 0.75, "source": "Ratio pluie 90 j / normale"},
    "alerts.rain_anomaly_critical": {"value": 0.50, "source": "Ratio pluie 90 j / normale"},
    "alerts.dam_fill_warning_pct": {"value": 50.0, "source": "Taux de remplissage des barrages"},
    "alerts.dam_fill_critical_pct": {"value": 30.0, "source": "Taux de remplissage des barrages"},
}


def quality(db: Session, key: str) -> str:
    """'official' when the ministry set the value, else the quality of the default (estimated / official)."""
    if db.get(PolicySetting, key) is not None:
        return "official"
    return DEFAULTS.get(key, {}).get("quality", "estimated")


def get(db: Session, key: str):
    row = db.get(PolicySetting, key)
    if row is not None:
        return row.value
    return DEFAULTS.get(key, {}).get("value")


def all_settings(db: Session) -> list[dict]:
    rows = {r.key: r for r in db.scalars(select(PolicySetting))}
    out = []
    for k, d in DEFAULTS.items():
        r = rows.get(k)
        out.append({"key": k, "value": r.value if r else d["value"], "status": r.status if r else "draft",
                    "source": (r.source if r and r.source else d["source"]),
                    "updated_at": r.updated_at.isoformat() if r else None})
    return out


def set_value(db: Session, key: str, value, user_id: int, validate: bool, source: str | None) -> PolicySetting:
    if key not in DEFAULTS:
        raise KeyError(key)
    row = db.get(PolicySetting, key) or PolicySetting(key=key)
    row.value = value
    row.status = "validated" if validate else "draft"
    row.source = source or DEFAULTS[key]["source"]
    row.updated_by = user_id
    db.add(row)
    db.commit()
    return row


def energy_policy(db: Session):
    from app.engines.energy import EnergyPolicy
    status = db.get(PolicySetting, "energy.injection_cap_pct")
    return EnergyPolicy(
        reserve_share=get(db, "energy.reserve_share"), crisis_min_soc=get(db, "energy.crisis_min_soc"),
        autonomy_hours=get(db, "energy.autonomy_hours"), injection_cap_pct=get(db, "energy.injection_cap_pct"),
        injection_cap_status=(status.status if status else "to_verify"),
        hypothesis_sale_pct=get(db, "energy.hypothesis_sale_pct"), pv_cost_tnd_kwp=get(db, "energy.pv_cost_tnd_kwp"),
        battery_cost_tnd_kwh=get(db, "energy.battery_cost_tnd_kwh"),
        grid_tariff_tnd_kwh=get(db, "energy.grid_tariff_tnd_kwh"),
        export_tariff_tnd_kwh=get(db, "energy.export_tariff_tnd_kwh"))
