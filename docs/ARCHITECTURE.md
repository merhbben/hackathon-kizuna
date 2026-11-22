# Architecture et méthodes

## Vue d'ensemble

```
React + TypeScript + Tailwind (Vite)          Leaflet + Geoman (dessin/édition), Recharts, i18next (FR / derja RTL)
            │  JWT Bearer, /api
FastAPI (Python)  ── auth/roles ── farms ── ministry ── reference
            │
   AgroBrain (engines/agrobrain.py) orchestre :
   climat → sol → aptitude → rendements → besoins en eau → MILP surfaces → découpage spatial
   → hydraulique/énergie par parcelle → planning CP-SAT → PV/batterie → chambres froides → contribution
            │
SQLAlchemy 2 + Alembic ── PostgreSQL/PostGIS (prod) | SQLite (dev/tests)
Connecteurs : World Bank, FAOSTAT, NASA POWER, Open-Meteo, PVGIS, SoilGrids, Sentinel-2 STAC
```

**Choix techniques**

- **Une seule application et un seul backend.** Les rôles `ministry` et `farmer` sont portés par le JWT. Un agriculteur ne voit que ses fermes. Le ministère voit l'agrégat national, à la manière de WAGRI.
- **Géométries stockées en GeoJSON.** La portabilité est assurée et Shapely/pyproj fait tous les calculs en UTM 32N (EPSG:32632, qui couvre la Tunisie). Sous PostgreSQL, des colonnes PostGIS `geom` sont maintenues par triggers, avec des index GIST, pour les requêtes spatiales.
- **Moteurs déterministes et explicables**, plutôt que des boîtes noires : FAO-56, MILP et CP-SAT. L'apprentissage automatique sert uniquement là où il est évaluable (prévisions, vision).
- **Provenance obligatoire.** Chaque donnée est un `DataRecord` qui porte `source`, `source_url`, `quality` (officielle, mesurée, estimée, prévision, manuelle) et `fetched_at`.

## Moteurs

| Module | Méthode |
|---|---|
| `fao56.py` | ET0 Penman-Monteith (FAO-56 éq. 6–40, validée sur l'exemple 18 : 3,9 mm/j) ; courbe Kc à 4 stades ; pluie efficace FAO/AGLW ; TAW/RAW avec ajustement de p ; fonctions de pédotransfert Saxton & Rawls (2006) ; triangle des textures USDA. |
| `suitability.py` | Gel (Tmin mensuelle), chaleur (palmier : Tmax de juillet ≥ 38 °C), salinité Maas-Hoffman (ECe ≈ 1,5·ECw), pH, pente, saison ; fraction de lessivage FAO-29 (goutte-à-goutte : ECw / 2·max ECe). |
| `forecast.py` | Demande par habitant = offre intérieure FAOSTAT / population, puis × projection World Bank. Rendements FAOSTAT. Modèles comparés : naïf, moyenne mobile 3, tendance linéaire, LightGBM et XGBoost sur un panel commun (variables sans échelle). Backtest à origine glissante sur les 4 dernières années. Sélection par MAPE et registre `model_runs` (métriques, version des bibliothèques, signature des données). Intervalle à 80 % issu des erreurs du backtest. |
| `optimizer.py` | MILP OR-Tools (SCIP). Variables : surfaces a_c et choix z_c. Contraintes : terre, eau **mensuelle** (débit × heures × jours), quota annuel, budget, part maximale par culture, nombre de cultures, parcelles verrouillées. Objectif : marge (si prix et coûts connus), productivité de l'eau, priorité nationale (dépendance aux importations FAOSTAT), rendement relatif. La terre non utilisée faute d'eau est signalée. |
| `partition.py` | Projection UTM ; retrait des exclusions et d'un recul périphérique ; Voronoï entre sources d'eau ; couloir principal (chemin et conduite) parallèle à l'axe long du rectangle orienté minimal et passant par le forage ; zone pompe. Les cultures sont triées par m³/ha décroissant et reçoivent **un bloc compact par région** par découpes récursives à surface exacte (treemap sur le vrai polygone) : la liste est coupée en deux groupes de surfaces équilibrées ; un petit groupe (≤ 35 %) prend un carré centré sur le forage, sinon la région est coupée en travers de son axe long et le groupe le plus gourmand prend le côté du forage ; chaque frontière est trouvée par **bissection**. Les terres non cultivées sont le bloc le plus éloigné. Ainsi une petite culture sur un grand terrain reste un bloc lisible (pas de bande de plusieurs km) et les cultures irriguées restent près du forage. Les blocs sont coupés en deux (surfaces égales, en travers de leur axe long) jusqu'à la taille de secteur : max(1 ha petite ferme / 4 ha grande, surface / 24). Une culture = une zone (A, B…) et ses secteurs sont A1, A2… (une seule étiquette par zone sur le plan, tableaux par zone, secteurs dépliables). Des chemins secondaires sont obtenus par buffer négatif. Les géométries sont validées par `make_valid`. |
| `hydraulics.py` | Hazen-Williams (PE, C = 140), choix du diamètre (vitesse ≤ 1,5 m/s), pertes singulières de 10 %. HMT = profondeur de pompage + dénivelé (pente × longueur) + pertes + pression de service. P = ρgQH/η ; kWh/m³. |
| `irrigation.py` | Bilan journalier par parcelle : Kc(jour) × ET0 (prévision Open-Meteo, sinon climatologie NASA POWER), pluie efficace. Goutte-à-goutte : apport quotidien. Aspersion et gravitaire : arrosage quand la déplétion atteint RAW. Le **CP-SAT** place les arrosages dans la fenêtre 05h–22h, sans chevauchement par source, en minimisant l'énergie non couverte par le PV et, pour l'aspersion, les heures chaudes et ventées. |
| `energy.py` | Profil horaire PVGIS seriescalc 2019–2023 (SARAH-3), moyenne par mois et par heure. Dimensionnement PV (pire mois ou bilan annuel). Batterie dimensionnée pour que la **réserve de crise** (entre `crisis_min_soc` et 1 − profondeur de décharge) couvre l'autonomie visée sur les charges vitales. Dispatch horaire : 20 % du PV d'abord vers la batterie (secours), puis les charges, puis la batterie (sans descendre sous le niveau de crise), puis le réseau. Le surplus est plafonné par le paramètre réglementaire. Le scénario à 80 % est uniquement une hypothèse. |
| `storage.py` | Chambre froide (conditions USDA HB66 ; méthode de charge ASHRAE : transmission, produit, respiration, infiltration, charges internes, marge de 10 %, fonctionnement 18 h/j ; COP égal à 0,45 × Carnot). Contribution d'une grande ferme : min(plafond, besoin_réserve / production_nationale × facteurs de capacité). Toujours au statut « proposition à valider ». |
| `cold_store.py` | **Bâtiment frigorifique de contre-saison**, obligatoire si la surface dépasse `storage.cold_building_min_ha` (65 ha, paramètre ministère). 1) Saison de manque = mois hors récolte nationale (calendrier indicatif : fenêtres de plantation + durée du cycle). 2) Période de stockage = récolte de la ferme → retour de la récolte nationale ou limite de conservation (USDA HB66), la première atteinte : on ne refroidit jamais après la fin du manque. 3) Candidates : cultures annuelles conservables au froid ≥ `storage.offseason_min_weeks` (8 sem.) ; score = mois de manque couverts × (1 + max(déficit national, dépendance aux importations)) × (0,5 + 0,5 × efficacité), efficacité = jours stockés dans le manque / jours stockés. Les 1 ou 2 meilleures présentes dans le plan sont retenues ; sinon la meilleure est imposée à l'optimiseur (surface minimale divisée par deux tant que l'eau ne le permet pas). 4) Chambres : une par culture, sauf deux cultures compatibles (|ΔT| ≤ 1 K, |ΔHR| ≤ 5 %) à périodes disjointes qui partagent une chambre dimensionnée pour la plus grande. Charges ASHRAE (`storage.cold_room`) comptées sur la seule période de stockage : maintien chaque jour + chaleur de la récolte pendant 14 jours de remplissage. Masse stockée = production × `storage.offseason_share_pct` (50 %). 5) Bâtiment = surface des chambres × 1,35, placé avec son champ PV près de l'entrée (sinon du forage) et retiré des cultures. 6) Énergie : deux scénarios simulés heure par heure avec le profil PVGIS du lieu. *Raccordé* : kWc = consommation annuelle (bilan net), batterie de secours seulement (`storage.cold_backup_hours`, 6 h). *Autonome* : kWc = mois le plus défavorable, batterie = déficit de nuit de ce mois (au-dessus de la réserve de crise) et au moins le secours. Recommandation : raccordé si la ferme déclare le réseau, sinon autonome. Le surplus mensuel du solaire du froid alimente les pompes du même mois (charges de jour), ce qui réduit l'installation solaire du pompage. |
| `national.py` | Bilan par culture et par année : besoin = demande × (1 + marge) + export − import ; production attendue = rendement prévu × surface récoltée moyenne. Hectares et eau « si irrigué » à partir de la médiane FAO-56 des 24 gouvernorats. Effet sur les prix qualitatif, quantitatif seulement si une élasticité est configurée. Allocation LP (GLOP) par gouvernorat **uniquement** si des capacités sont connues (import ONAGRI/CRDA ou fermes inscrites). Simulations : pluie (Ky FAO-33), population, rendements, coupure des imports, marge. Alertes : pluie sur 90 jours comparée à la normale (NASA POWER daily), barrages, déficits et surplus, autonomie des chambres froides. |

## Vision par ordinateur (`app/cv`)

1. Lecture d'une image, ou du PDF avec PyMuPDF à 200 dpi. Les fichiers géographiques (GeoJSON, KML, GPKG, Shapefile en zip) passent par GeoPandas et sont déjà géoréférencés.
2. OpenCV : filtre bilatéral, Canny et seuil adaptatif, fermeture morphologique, plus grand contour (hors cadre), Douglas-Peucker. Indice de confiance fondé sur la solidité et la surface.
3. Éléments internes : Hough probabiliste pour les chemins et canaux, HSV bleu pour l'eau, blobs sombres pour les bâtiments, Hough cercles pour les puits.
4. L'agriculteur corrige le contour dans l'éditeur (glisser, ajouter, supprimer des sommets).
5. Géoréférencement par 2 points d'appui (similitude) ou 3 et plus (affine par moindres carrés, avec résidus en mètres), ou par échelle, ancre et rotation.
6. Vérification de la surface : mesurée contre déclarée (tolérance de 10 %) et contrôle du gouvernorat. **La planification est bloquée tant que la surface n'est pas confirmée.**
7. Un modèle de segmentation U-Net (PyTorch) est fourni avec son script d'entraînement et une évaluation IoU, mais **sans poids**, faute de corpus étiqueté public (voir STATUS).

## Sécurité

- Mots de passe hachés avec bcrypt (12 rounds) ; JWT HS256 avec expiration ; limitation des tentatives de connexion (5 échecs par 15 min).
- Rôles vérifiés côté serveur, cloisonnement des fermes par propriétaire, création des comptes du ministère par CLI uniquement.
- Validation Pydantic de toutes les entrées, uploads limités en taille et en extension, zip protégé contre le *path traversal*.
- En-têtes de sécurité, erreurs 500 sans trace de pile, journal d'audit (`audit_log`), secret obligatoire en production.
