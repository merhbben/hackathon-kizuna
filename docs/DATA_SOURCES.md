# Sources de données

| Source | Contenu | Accès | Qualité affichée | Statut |
|---|---|---|---|---|
| **FAOSTAT** – Food Balance Sheets (FBS) | Offre intérieure, production, importations, exportations, variation des stocks, kcal et protéines par habitant (2010–2023) | Bulk `bulks-faostat.fao.org/production/FoodBalanceSheets_E_Africa.zip`, filtré sur la zone 222 | Officiel, ou Estimé si le drapeau FAO vaut E ou I | ✅ Intégré (extrait inclus, actualisable) |
| **FAOSTAT** – QCL | Surfaces récoltées, rendements et production par culture (1961–2024) | Bulk `Production_Crops_Livestock_E_Africa.zip` | idem | ✅ Intégré |
| **World Bank** | Population (WDI) et projections jusqu'en 2050 (source 40) | `api.worldbank.org/v2/country/TUN/indicator/SP.POP.TOTL` | Officiel / Prévision | ✅ Intégré |
| **NASA POWER** | Climatologie mensuelle (Tmax, Tmin, HR, vent, rayonnement, pluie) ; pluie quotidienne récente | `power.larc.nasa.gov/api/temporal/{climatology,daily}/point` | Estimé (réanalyse) | ✅ Intégré (24 gouvernorats + chaque ferme) |
| **Open-Meteo** | Prévision à 7 jours de l'ET0 FAO, de la pluie et des températures | `api.open-meteo.com/v1/forecast` | Prévision | ✅ Intégré (repli sur la climatologie en cas de quota) |
| **PVGIS 5.3** (JRC) | Production PV horaire par kWc (SARAH-3, 2019–2023, inclinaison optimale) | `re.jrc.ec.europa.eu/api/v5_3/seriescalc` | Estimé | ✅ Intégré |
| **SoilGrids 2.0** (ISRIC) | Argile, sable, limon, pH, carbone organique (0–30 cm, 250 m) | `rest.isric.org/soilgrids/v2.0/properties/query` | Estimé | ✅ Intégré (bouton « Remplir automatiquement ») |
| **Sentinel-2 L2A** | Recherche des scènes récentes sur l'emprise de la ferme | STAC Element84 `earth-search.aws.element84.com/v1/search` | — | ⚠️ Découverte des scènes seulement ; NDVI non calculé |
| **geoBoundaries** | Limites des 24 gouvernorats (ADM1) | gbOpen TUN ADM1 (ODbL, OpenStreetMap) | — | ✅ Inclus |
| **INS** | Population par gouvernorat (RGPH 2024) | Pas d'API publique : import CSV | Officiel (importé) | 📥 Import manuel |
| **ONAGRI / CRDA / data.gov.tn** | Barrages (réserves et capacité), surfaces irriguées, rendements régionaux, allocations d'eau | Bulletins PDF/XLS : import CSV | Officiel (importé) | 📥 Import manuel |
| **INM** | Stations météo | Pas d'API publique : import CSV | Mesuré | 📥 Import manuel |
| **FAO WaPOR v3** | ET réelle et productivité de l'eau (raster) | API raster | — | ⏳ Non intégré (nécessite une chaîne raster) |
| **Décret n° 2026-66** (SMAG) | Salaire minimum agricole garanti : 21,336 DT/jour au 1er janvier 2026 | Texte réglementaire | Officiel | ✅ Paramètre `costs.smag_tnd_day` |
| **Prix des engrais** | Ammonitrate 720 DT/t (prix de détail fixé, campagne 2024-2025) ; DAP 690 DT/t (dernier prix public relevé, 2021, à actualiser) | Presse économique (décisions du ministère) | Officiel / Estimé | ✅ Paramètres `costs.*` |
| **BPEH – Rapport national du secteur de l'eau 2020** | Coût moyen de l'eau d'irrigation 0,110 DT/m³ (cité par l'étude GIZ sur les bonnes pratiques économes en eau) | Rapport | Officiel | ✅ Paramètre `costs.network_water_tnd_m3` |
| **IRESA – Recueil des fiches technico-économiques** (tomes I et II) | Charges et marges par culture et par région | Non accessible en ligne en texte | — | ⏳ À intégrer : remplacera les coefficients estimés du modèle de coûts |
| **ANME / STEG** | Règles photovoltaïques et tarifs | Textes réglementaires | Paramètres ministère | ⚙️ Paramétrable (voir ci-dessous) |

## Import manuel (CSV)

Le menu Ministère › Alertes et gestion › Données accepte un CSV avec les colonnes suivantes :

```
indicator,entity,item,period,value,unit,quality,source_url,note
dam_storage_mm3,TN-31,Sidi Salem,2026-11-20,250.3,Mm3,official,https://www.onagri.nat.tn/...,
irrigated_area_ha,TN-41,,2024,…,ha,official,https://…,
yield_kg_ha,TN-41,tomato,2024,…,kg/ha,official,https://…,
```

`entity` vaut `TN` ou un code ISO de gouvernorat (`TN-11` … `TN-83`). `source_url` est **obligatoire**. Indicateurs reconnus : `irrigated_area_ha`, `water_allocation_mm3`, `dam_storage_mm3`, `dam_capacity_mm3`, `population`, `yield_kg_ha`, `reserve_stock_kt`, `cold_storage_capacity_t`.

## Paramètres réglementaires (énergie)

- **Plafond de vente des excédents à la STEG**, valeur par défaut de 30 % de la production annuelle. Références : décret n°2020-105, qui modifie le décret n°2016-1123 pris en application de la loi n°2015-12 modifiée par la loi n°2019-47. Le statut affiché est « à vérifier » : l'application exacte dépend du contrat, du niveau de tension et du régime (BT ou MT/HT). Le ministère peut modifier et valider ce paramètre.
- **Scénario de vente à 80 %** : il est toujours affiché comme une **hypothèse non autorisée**.
- Les tarifs STEG, les coûts PV, batterie et chambre froide, ainsi que les prix et coûts agricoles, sont **vides par défaut**. Ils sont saisis par le ministère ou par l'agriculteur, avec leur source. En leur absence, les montants affichent « à renseigner » et le critère économique de l'optimiseur est désactivé, son poids étant redistribué.

## Valeurs de référence agronomiques (codées, avec références)

Le fichier `backend/app/knowledge/crops.py` contient, pour 17 cultures : Kc, durées des stades, profondeur racinaire et p (FAO-56) ; Ky (FAO-33) ; seuils et pentes de salinité (FAO-29, Maas & Hoffman) ; conditions de conservation (USDA HB66) ; chaleur de respiration (ASHRAE). Les durées des stades et les calendriers sont des valeurs méditerranéennes adaptées, marquées `calibrate=True`, **à valider par les CRDA et l'INRAT**.
