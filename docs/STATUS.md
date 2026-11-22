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

## Module de planification 2D (Mon plan agricole) — version 2

Organisation : **entrée du modèle** (terrain tel que fourni) à gauche → **sortie du modèle** (même terrain découpé en parcelles A, B, C…) à droite → tableaux A à E en dessous, sur une seule page. Sur mobile, les panneaux s'empilent.

- ✅ **Saisie réduite** : contour (plan importé ou dessin sur carte), longueur d'un côté si l'échelle est illisible, GPS/gouvernorat/délégation, entrée, forages F1…Fn (position par clic, débit, profondeur, puissance de pompe, volume/quota, autorisation), réseau électrique, tarif de la facture, PV et batteries existants, méthode d'irrigation, chambre froide. Aucune saisie de météo, d'ET0, de besoins en eau, de cultures ou de surfaces. Les valeurs inconnues restent vides et sont listées (« À compléter »).
- ✅ **Climat automatique** (`GET /api/farms/{id}/climate`), avec source, période, résolution et date pour chaque couche :
  - normales NASA POWER 2001–2025 (T moy/min/max, pluie, humidité, vent, rayonnement, ET0 FAO-56) ;
  - statistiques ERA5/ERA5-Land sur 10 ans (variabilité de la pluie, année sèche, probabilité de gel, jours ≥ 35 °C, fortes pluies) ;
  - observations des 30 derniers jours (ERA5) ;
  - prévision à 7 jours (Open-Meteo) ;
  - indice d'aridité et risques ;
  - sol SoilGrids, marqué comme estimation.
- ⏳ **INM** : pas d'API publique ; c'est indiqué dans l'application, et l'import CSV reste possible.
- ✅ **Plantation selon le climat** : pour les cultures sensibles au gel, première date de la fenêtre dont le cycle évite les mois où le gel survient au moins une année sur cinq (ERA5-Land).
- ✅ **Calendrier** : phases FAO-56 et rotation vers une autre famille botanique (légumineuse après une culture exigeante).
- ✅ **Énergie de pompage** : avec la puissance réelle de la pompe et le débit, l'énergie vaut kW / débit ; sinon elle vient du calcul hydraulique, et sinon c'est un minimum signalé.
- ✅ **Tableaux A–E** (`GET /api/farms/{id}/plans/{pid}/report`) :
  - A : répartition (surface, %, eau, production, irrigation, distance au forage) ;
  - B : programme d'irrigation (CP-SAT, jours et heure, durée, énergie, totaux hebdomadaires et saisonniers, sans conflit de pompe) ;
  - C : calendrier ;
  - D : énergie (pompage, puissance appelée, répartition solaire/batterie/réseau, coût si le tarif est connu) ;
  - E : production, récoltes, stockage froid selon le produit, panneaux et batteries, marge si les prix sont connus.
- ✅ **Conservation du terrain** : le contour exact est conservé. Les parcelles sont valides, sans chevauchement et contenues dans le terrain (testé).
- ✅ **Échelle par un côté** : donner la longueur réelle d'un côté remet tout le plan à l'échelle (surface × f², testé).
- ⚠️ **Durée d'un import image** : de 60 à 100 s (OCR + premier téléchargement du climat). Les imports vectoriels sont plus rapides.
- ✅ **Saisie minimale** : contour (plan ou carte), localisation, surface, ressources en eau et énergie. Le sol n'est plus saisi : il est lu sur le plan s'il y figure, sinon il vient de SoilGrids d'après la position (texture par défaut signalée si SoilGrids ne répond pas). Saison, budget et cultures existantes ont été retirés des formulaires.
- ✅ **Pipeline visible** (« Comment votre plan a été calculé ») : entrées → climat, aptitude, eau disponible, optimisation, découpage, irrigation/énergie → plan, avec les chiffres réels du terrain et le facteur limitant expliqué.
- ✅ **Recalcul automatique** : une empreinte des entrées est enregistrée avec chaque plan, et le plan est recalculé à l'ouverture si le terrain ou les ressources ont changé.
- ✅ **Quota d'eau par source** : une source sans quota n'est plus bridée par le quota d'une autre.
- ✅ **Terres non irrigables** : elles sont proposées en cultures pluviales quand le climat le permet. Bilan hydrique FAO-56 ch. 8 (réserve du sol, Ks, pluie USDA-SCS) puis FAO-33 (Ky) ; une culture n'est proposée que si son rendement atteint au moins 50 % du potentiel. Ces parcelles n'ont ni irrigation ni conduite.
- ✅ **Plan lisible** : une culture = une zone (A, B…) avec une seule étiquette et sa surface totale ; ses secteurs d'irrigation sont A1, A2… (dépliables dans les tableaux A et B). Les blocs sont compacts (découpe récursive à surface exacte), les cultures irriguées sont groupées autour des forages et la taille de secteur suit la surface du terrain (≈ 24 secteurs maximum). Exemple : terrain de 1 230 ha passé de 283 parcelles en bandes à 6 zones et 46 secteurs.
- ✅ **Bâtiment frigorifique de contre-saison (> 65 ha)** : une ou deux cultures fraîches choisies selon les mois où le pays en manque (calendrier national indicatif, déficit et importations FAOSTAT, efficacité du stockage), imposées au plan si besoin. Le froid s'arrête quand la récolte nationale revient ; chambres partagées quand les conditions sont compatibles et les périodes disjointes ; bâtiment et champ solaire dessinés sur le plan. Énergie étudiée en deux scénarios heure par heure (raccordé / autonome) avec recommandation selon le réseau ; le surplus solaire du froid alimente les pompes. Exemple Béja 1 230 ha (réseau déclaré) : oignon + carotte, 2 chambres (humidités incompatibles), 900 m³, 30,5 MWh/an (111 kWh/t) ; raccordé 20 kWc + 172 kWh de secours (100 % en bilan annuel) contre 55 kWc + 311 kWh en autonome ; 8,1 MWh/an de surplus vers les pompes. ⚠️ Seuil de 65 ha, part stockée (50 %), 6 h de secours et calendrier national : paramètres à valider par le ministère / CRDA ; coûts PV et batterie à renseigner.
- ✅ **Contrôle de cohérence des pompes** : une alerte s'affiche si la puissance déclarée dépasse 3 fois le besoin hydraulique (probable erreur de saisie).
- ⚠️ **Petites parcelles** : quand l'eau limite fortement la surface, le découpage par secteurs produit des parcelles de petite taille.
- ⚠️ **Image de référence** : l'image annoncée dans la demande n'a pas été reçue. La disposition suit la description écrite (deux panneaux, tableaux dessous).

## Import d'un plan technique (un seul fichier) → plan agricole 2D interactif

Chaîne réelle : **Importer → Lire → Comprendre → Vérifier → Optimiser → Afficher (Phaser) → Calculer → Enregistrer / exporter**.

- ✅ Lecture **vectorielle** (PDF, SVG) : contour, cotes, échelle, forages, zones (bassin, PV, bâtiments, froid, verger, zone exclue), chemins, conduites, talus, textes. Les étiquettes dessinées en contours (non textuelles) sont lues par OCR local (RapidOCR/ONNX).
- ✅ Lecture **image** (PNG/JPG couleur ou noir & blanc, PDF scanné) : OpenCV (graphe de lignes épaisses → coins → plus grand cycle, ordonné par les bornes B1…Bn) + OCR ; échelle calée sur les graduations de la barre d'échelle ; seuillage d'Otsu pour traiter la couleur comme du noir & blanc.
- ✅ Jamais de confusion contour / cadre de page / barre d'échelle / cotes (testé sur les 16 fichiers).
- ✅ Évaluation chiffrée : `docs/EVALUATION.md` (16/16 plans lus ; vectoriel exact ; images ≤ 0,7 % de surface, ≤ 2,1 m sur les forages).
- ✅ Vérification : surface mesurée comparée à la surface imprimée (tolérance 3 %) ; échelle déduite de la surface imprimée si la barre est illisible (signalé).
- ✅ Aucune valeur inventée : chaque élément absent produit un avertissement précis (GPS, débit, profondeur, saison, sol…) ; corrections facultatives puis recalcul complet.
- ⚠️ **Plans d'essai sans GPS** : terrain placé au centre du gouvernorat (« position approximative ») → climat/sol approximatifs tant que l'agriculteur ne corrige pas.
- ⚠️ **Débit de pompe absent des plans d'essai** : volumes d'eau calculés (FAO-56) mais durées/horaires d'arrosage non calculés et énergie de pompage = minimum (profondeur inconnue). Ajouter le débit dans « Corrections » active le planning CP-SAT.
- ✅ Eau déclarée (m³/jour) utilisée comme contrainte dure mensuelle de l'optimiseur (testé).
- ✅ Éditeur 2D **Phaser 3** dans React : vrais polygones à l'échelle, parcelles colorées, zones, forages, conduites proposées, terres non cultivées (eau insuffisante), zoom molette/pinch/boutons, déplacement, sélection, changement de culture → recalcul ; responsive PC/mobile, FR/derja.
- ✅ Exports : PNG (capture Phaser), SVG et PDF (rendu serveur à l'échelle avec légende, échelle graphique, nord), GeoJSON ; **Enregistrer** (.agrosphere.json) et **Ouvrir** un plan enregistré (aller-retour sans perte, testé).
- ⏳ Cotes manuscrites et plans sans bornes B1…Bn : non évalués (pas de corpus) ; modèle de segmentation profond non utilisé car sans gain démontré sur ces plans (le pipeline classique est exact).
- ⏳ Modification de la *forme* d'une parcelle dans Phaser : non exposée (l'API la supporte).
