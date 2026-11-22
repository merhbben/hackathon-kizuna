/** Pipeline entrées → modèles → plan optimisé. */
const plfr = {
  title: "Comment votre plan a été calculé", sub: "Entrées de votre terrain → modèles AgroBrain → plan optimisé (chiffres réels de ce terrain)",
  inputs: "Vos entrées", fromPlan: "Plan importé", fromMap: "Dessin sur la carte", vertices: "sommets", location: "Position",
  loc_user: "GPS donné", loc_plan_gps: "GPS lu sur le plan", loc_governorate_centroid: "approximative (centre du gouvernorat)", loc_missing: "manquante",
  sources: "{{n}} source(s)", quota: "Quota", pumps: "Pompes",
  models: "Modèles AgroBrain", climate: "Climat (NASA POWER, ERA5)", frost: "Gel possible {{n}} mois", noFrost: "Pas de risque de gel notable",
  suitability: "Cultures adaptées", suitable: "{{n}} cultures adaptées sur {{of}}", excluded: "Écartées",
  water: "Eau disponible", available: "Disponible", quotaShort: "quota", pumping: "capacité de pompage", needAll: "Il faudrait pour tout irriguer", used: "Utilisée par le plan",
  optimisation: "Optimisation (OR-Tools)", irrigated: "Irrigué", rainfed: "Pluvial", unused: "Non cultivé", limit: "Facteur limitant",
  lim_quota: "quota d'eau", lim_water: "eau du mois {{m}}", lim_land: "surface du terrain", lim_budget: "budget", lim_none: "aucun",
  partition: "Découpage (Shapely)", parcels: "{{n}} parcelles", infra: "Chemins et conduites", nearSources: "Cultures gourmandes près des forages",
  irrigEnergy: "Irrigation et énergie (FAO-56, CP-SAT)", season: "Saison", noConflict: "Aucun conflit de pompe", pvReco: "Solaire recommandé",
  output: "Plan optimisé", crops: "{{n}} cultures", cultivated: "Cultivé",
  whyQuota: "Votre quota de {{avail}} m³/an limite l'irrigation : il faudrait environ {{need}} m³ pour irriguer tout le terrain. AgroBrain irrigue donc {{irr}} ha, met {{rf}} ha en cultures pluviales et laisse {{un}} ha non cultivés. Augmenter le quota ou ajouter une source change le plan.",
  whyWater: "L'eau disponible certains mois ({{avail}} m³/an au total) limite l'irrigation : il faudrait environ {{need}} m³. AgroBrain irrigue {{irr}} ha, met {{rf}} ha en pluvial et laisse {{un}} ha non cultivés. Un débit ou un volume plus élevé change le plan.",
  soilDefault: "par défaut : SoilGrids n'a pas répondu",
  recomputing: "Le terrain ou les ressources ont changé : AgroBrain recalcule votre plan…",
  stale: "Ce plan a été calculé avec d'anciennes données du terrain.",
};
export default plfr;
