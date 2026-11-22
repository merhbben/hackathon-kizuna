/** Coût de production calculé automatiquement (modèle par postes). */
const cofr = {
  title: "Coût de production (calcul automatique)",
  sub: "Calculé pour chaque culture de votre plan, poste par poste : rien à saisir",
  perHa: "Coût / ha", area: "Surface", total: "Coût total", main: "Principaux postes", detail: "détail",
  item: "Poste", qty: "Quantité / ha", unitPrice: "Prix unitaire", quality: "Qualité",
  i_labour: "Main-d'œuvre", i_seed: "Semences / plants", i_ammonitrate: "Ammonitrate 33,5 %", i_dap: "DAP 18-46",
  i_potash: "Sulfate de potasse", i_treatments: "Traitements", i_mechanisation: "Mécanisation", i_energy: "Énergie de pompage",
  i_water: "Eau du réseau", i_drip: "Goutte-à-goutte (entretien)",
  u_day: "jours", u_kg: "kg", u_plant: "plants", u_t: "t", u_treatment: "traitements", u_h: "h", u_kWh: "kWh", u_m3: "m³", u_ha: "ha",
  q_official: "officiel", q_estimated: "estimé", q_measured: "votre terrain", q_missing: "manquant",
  priceMissing: "prix à renseigner",
  basisLine: "Base de calcul pour ce terrain : rendement attendu {{y}} t/ha · eau {{w}} m³/ha · {{d}} jours de travail/ha · besoins N {{n}}, P₂O₅ {{p}}, K₂O {{k}} kg/ha.",
  tariffMissing: "Tarif d'électricité non renseigné : l'énergie de pompage n'est pas chiffrée (indiquez le tarif STEG dans « Modifier les données »).",
  ministryRef: "Coût de référence fixé par le ministère pour cette culture.",
  method: "Méthode : main-d'œuvre = jours/ha (y compris la récolte, proportionnelle au rendement) × SMAG 21,336 DT/jour (décret 2026-66) ; engrais = besoins de la culture pour le rendement attendu, convertis en DAP, ammonitrate (720 DT/t, prix fixé 2024-2025) et potasse ; énergie = eau d'irrigation × énergie de VOTRE pompe × votre tarif ; eau du réseau 0,110 DT/m³ (BPEH 2020). Les quantités techniques par culture et les prix marqués « estimé » sont des valeurs indicatives, à remplacer par les fiches technico-économiques IRESA / CRDA ; le ministère peut les modifier.",
  autoHint: "calcul automatique (estimé)", officialHint: "coûts de référence du ministère",
  recompute: "Coûts non encore calculés pour ce plan : recalculez le plan.",
  pricesTitle: "Prix de vente (facultatif)", pricesSub: "Pour estimer le revenu et la marge ; les coûts sont calculés automatiquement",
};
export default cofr;
