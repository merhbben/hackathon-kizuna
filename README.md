# TuniNō

**TuniNō — Two nations, one vision: sustainable agriculture**

TuniNō est une plateforme unique inspirée de **WAGRI** (Japon). Elle centralise et partage les données agricoles pour deux publics :

- **Ministère de l'Agriculture (Tunisie)** : il suit le bilan national (besoins alimentaires, production, importations et exportations, réserves, eau et énergie). Il planifie la production par culture, gouvernorat et saison avec une marge de sécurité, simule des scénarios et valide les propositions.
- **Agriculteurs (petites et grandes exploitations)** : à partir du terrain réel (dessin sur la carte ou plan 2D importé et reconnu par vision par ordinateur), **AgroBrain** produit un plan découpé en parcelles colorées. Ce plan comprend les cultures, les surfaces, la production, les besoins en eau et en énergie, les dates, le programme d'arrosage, le dimensionnement solaire et batterie, ainsi que les chambres froides et la contribution aux réserves.

L'interface est bilingue, **Français / تونسي** (derja en écriture arabe, mise en page RTL), et s'adapte au PC, à la tablette et au mobile.

> Chaque chiffre affiché porte sa provenance : **Officiel**, **Mesuré**, **Estimé** ou **Prévision**. Aucune valeur n'est inventée. Les données manquantes sont listées et s'importent par CSV, avec une source obligatoire.

---

## Mon plan agricole : terrain → plan optimisé

L'agriculteur donne seulement son terrain : il importe un plan (PNG, JPG, PDF ou SVG) ou le dessine sur la carte. Il ajoute sa position, ses forages (débit, profondeur, pompe) et ses équipements énergétiques. Il ne saisit ni la météo ni les besoins en eau.

AgroBrain récupère automatiquement le climat du lieu (NASA POWER, ERA5/ERA5-Land, Open-Meteo) et le sol (SoilGrids). Il renvoie **le même terrain** découpé en parcelles A, B, C… : cultures optimisées par OR-Tools, découpage Shapely, irrigation FAO-56 planifiée par CP-SAT.

Sur une seule page, sous les deux panneaux « Entrée du modèle » et « Plan optimisé », s'affichent :
- la répartition des cultures ;
- le programme d'irrigation ;
- le calendrier cultural ;
- l'énergie ;
- les récoltes et le stockage ;
- au-delà de 65 ha, le **bâtiment frigorifique de contre-saison** : une ou deux cultures fraîches gardées jusqu'aux mois où le pays en manque, avec son installation solaire dédiée (scénarios raccordé / autonome simulés heure par heure).

Une culture = une zone (A, B…) avec une seule étiquette ; ses secteurs d'irrigation (A1, A2…) se déplient dans les tableaux.

Statut détaillé : [docs/STATUS.md](docs/STATUS.md). Évaluation de la lecture des plans : [docs/EVALUATION.md](docs/EVALUATION.md).

## Démarrage rapide (développement local, Windows / Linux / macOS)

Prérequis : Python 3.10 ou plus, Node 20 ou plus. En développement, la base est SQLite ; en production, PostgreSQL/PostGIS via Docker.

```bash
# 1. Backend
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip      # (Linux/macOS : .venv/bin/python)
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/alembic upgrade head                      # migrations
.venv/Scripts/python -m app.cli bootstrap               # données réelles + entraînement/sélection des modèles
.venv/Scripts/python -m app.cli create-user --email ministere@exemple.tn --name "Direction de la planification" --role ministry
.venv/Scripts/python -m uvicorn app.main:app --port 8000

# 2. Frontend (autre terminal)
cd frontend
npm install
npm run dev            # http://localhost:5173 (proxy /api -> :8000)
```

Les agriculteurs créent leur compte eux-mêmes depuis l'écran de connexion. Les comptes du ministère sont créés uniquement par la commande `create-user`.

`bootstrap` charge :
- FAOSTAT (bilans alimentaires et production, Tunisie, code zone 222), à partir de l'extrait inclus dans `backend/data/reference`. Les valeurs avec le drapeau FAO « E » ou « I » sont marquées *estimées*.
- La population World Bank (historique et projections, source 40).
- Le climat NASA POWER pour les 24 gouvernorats, avec l'ET0 calculée selon FAO-56 Penman-Monteith.

Il lance ensuite le backtest des modèles de prévision.

> **Réseau d'entreprise ou antivirus avec inspection TLS (Avast…)** : le backend utilise `truststore`, qui s'appuie sur le magasin de certificats du système. Pour `pip`, mettez-le d'abord à jour (`pip ≥ 24.2` utilise aussi le magasin système). Pour `npm`, utilisez `NODE_OPTIONS=--use-system-ca` (Node ≥ 23.8).

## Production (Docker)

```bash
cp .env.example .env      # définir POSTGRES_PASSWORD et AGRO_JWT_SECRET (>= 32 caractères aléatoires)
docker compose up -d --build
docker compose exec backend python -m app.cli bootstrap
docker compose exec backend python -m app.cli create-user --email ... --name ... --role ministry
# http://localhost:8080
```

En production, le backend refuse de démarrer avec un secret JWT par défaut. La migration PostgreSQL crée l'extension PostGIS, des colonnes `geom` (EPSG:4326) alimentées par trigger et des index GIST.

## Tests

```bash
cd backend && .venv/Scripts/python -m pytest -q     # 71 tests : FAO-56, Saxton-Rawls, hydraulique, MILP, découpage, lecture de plans,
                                                     # CP-SAT, solaire, froid, contre-saison (> 65 ha), coûts de production, climat, calendrier, tableaux A–F, API, rôles
cd frontend && npm test                              # parité FR/derja, clés utilisées, écriture arabe
cd frontend && npm run build                         # typecheck + build
```

Les tests n'utilisent pas le réseau. Les connecteurs sont remplacés par des fixtures clairement marquées « TEST ». Les tests de prévision utilisent l'extrait FAOSTAT réel.

## Organisation

```
backend/
  app/api/          auth, farms (agriculteur), ministry, reference
  app/connectors/   World Bank, FAOSTAT, NASA POWER, ERA5 / Open-Meteo (climate.py), PVGIS, SoilGrids, Sentinel-2 STAC
  app/cv/           plan_reader (OpenCV, PDF, GeoPandas, géoréférencement), segmentation (U-Net PyTorch optionnel)
  app/engines/      fao56, suitability, forecast, optimizer (MILP), partition (Shapely), hydraulics,
                    irrigation (CP-SAT), energy, storage, national (LP), policy, agrobrain (orchestrateur)
  app/knowledge/    catalogue des cultures (FAO-56/29/33, USDA HB66), gouvernorats
  alembic/          migrations (+ PostGIS)
  tests/
frontend/
  src/pages/ministry   Accueil national · Planifier les cultures · Réserves et énergie · Alertes et gestion
  src/pages/farmer     Mon plan agricole (entrée → plan optimisé → tableaux A–F) · Eau et énergie · Récoltes et stockage · Données du terrain
  src/i18n             fr.ts, ar.ts (derja)
docs/                  ARCHITECTURE.md · DATA_SOURCES.md · STATUS.md
```

Voir [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) pour les méthodes, [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) pour les données et [docs/STATUS.md](docs/STATUS.md) pour le statut exact de chaque fonctionnalité.
