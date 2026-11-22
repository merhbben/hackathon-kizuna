# Statut exact des fonctionnalités

Légende : ✅ fonctionnel et testé · ⚠️ fonctionnel avec limite connue · 📥 dépend de données à importer · 🏛️ dépend d'une validation institutionnelle · ⏳ non réalisé

## Plateforme
- ✅ Authentification JWT, rôles ministère/agriculteur, cloisonnement des données, audit, limitation des tentatives de connexion.
- ✅ Base de données et migrations Alembic. Sous PostgreSQL, triggers PostGIS et index GIST (⚠️ la migration PostGIS est écrite mais n'a pas pu être exécutée ici : Docker et PostgreSQL ne sont pas installés sur la machine de développement. Seul le chemin SQLite a été exécuté).
- ⚠️ Docker Compose (PostGIS, backend, nginx) écrit mais **non testé ici**, faute de Docker sur la machine.
- ✅ Bilinguisme FR / derja (RTL), avec un test automatique de parité des clés.
- ✅ Responsive (barre de navigation basse sur mobile).

## Ministère
- ✅ Bilan national 2010–2023 (FAOSTAT) et prévisions (World Bank et modèles sélectionnés par backtest).
- ✅ Objectifs par culture et saison : besoin, production attendue, écart, hectares, eau « si irrigué », réserve, pression sur les prix (qualitative).
- 📥 Répartition par gouvernorat (LP OR-Tools) : elle s'active quand les surfaces irrigables et les allocations d'eau sont importées (ONAGRI/CRDA) ou à partir des fermes inscrites. Sans ces données, l'application affiche le besoin en eau par gouvernorat (FAO-56 et NASA POWER) et explique ce qui manque.
- ✅ Alertes de sécheresse (NASA POWER, pluie sur 90 jours), de déficit et de surplus, de chambres froides sans secours.
- 📥 Alertes sur les barrages : elles fonctionnent dès que la situation ONAGRI est importée.
- ✅ Simulations (pluie, population, rendements, importations, marge).
- 🏛️ Contributions des grandes exploitations : calculées et proposées. **Elles ne deviennent effectives qu'après validation** par l'autorité compétente (bouton Valider ou Refuser, journalisé). Les seuils de « grande exploitation » (50 ha / 3 forages) et le plafond (10 %) sont des **brouillons** à valider.
- 📥 L'effet chiffré sur les prix exige des élasticités configurées. Sans elles, seule la direction est indiquée.
- ⚠️ Les bilans FBS sont des estimations de la FAO (drapeau E), affichées comme « Estimé ».

## Agriculteur
- ✅ Contour dessiné sur la carte (Geoman), import GeoJSON/KML/GPKG/Shapefile, vérification de la surface et du gouvernorat.
- ✅ Import d'image ou de PDF : détection OpenCV du contour, des chemins, des bâtiments, de l'eau et des puits, correction manuelle, géoréférencement par 2 points ou plus, ou par échelle et ancre.
- ⚠️ La détection classique fonctionne sur des plans nets (contour tracé). Sur des photos de plans manuscrits ou très chargés, il faut corriger manuellement le contour.
- ⏳ Segmentation profonde (U-Net) : code d'architecture, d'entraînement et d'évaluation IoU fourni, **aucun poids entraîné**, faute de jeu de données étiqueté de plans tunisiens.
- ✅ Recommandation de cultures (aptitude, saison, salinité), MILP des surfaces avec contraintes d'eau mensuelles, découpage spatial à surface exacte avec les cultures les plus gourmandes en eau près des sources, zones techniques.
- ✅ Modification d'une parcelle (culture) : la parcelle est verrouillée et tout le plan est recalculé (nouvelle version).
- ⚠️ Modification de la *forme* d'une parcelle : prise en charge par l'API (`edits[].geometry`), mais l'interface n'expose pour l'instant que le changement de culture.
- ✅ Irrigation FAO-56 par parcelle, programme sur 7 jours (prévision Open-Meteo) et semaine de pointe, planning CP-SAT sans conflit de pompe et favorisant le solaire, calendrier mensuel.
- ✅ PV (PVGIS horaire), batterie avec réserve de crise, stratégie de 20 % réservés, autonomie, surplus dans le plafond réglementaire configurable, scénario à 80 % marqué comme hypothèse.
- ✅ Chambres froides : capacité, température et humidité, charge thermique mensuelle, électricité, et coût si un prix au m³ est configuré.
- 📥 Coûts et revenus : calculés dès que les prix et coûts sont renseignés (par l'agriculteur ou les références du ministère).
- ⚠️ Rendements : moyenne nationale FAOSTAT (qui mélange cultures pluviales et irriguées), remplacée par les rendements régionaux importés ou par ceux de l'agriculteur. Plusieurs rendements FAOSTAT de cultures maraîchères sont des estimations de la FAO (drapeau E) et sont affichés comme tels.
- ⚠️ Sentinel-2 : recherche des scènes récentes seulement (`/api/farms/{id}/satellite`). Le calcul du NDVI n'est pas implémenté (il faudrait rasterio).

## Modèles : résultats du dernier backtest (réel, `python -m app.cli bootstrap`)
Sur les séries annuelles FAOSTAT (14 points pour la demande), les méthodes simples (tendance linéaire, naïf, moyenne mobile) **battent souvent** LightGBM et XGBoost. Le registre retient le meilleur modèle pour chaque culture et conserve toutes les comparaisons. Exemples : demande de blé, tendance linéaire, MAPE 2,8 % ; pomme de terre, LightGBM, 3,9 %. Les MAPE quasi nulles sur certains rendements reflètent des séries FAO estimées et lissées, pas une vraie précision.

## Limites géographiques
- ⏳ Évaluation spatiale de type *leave-one-governorate-out* des rendements : elle requiert des rendements par gouvernorat, qui ne sont pas disponibles en données ouvertes et s'importent par CSV.
