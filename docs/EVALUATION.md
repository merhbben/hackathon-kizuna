# Évaluation de la lecture des plans

Généré par `python -m app.cv.evaluate` (backend). Jeu d'essai : `backend/tests/fixtures/plans`, 4 plans
synthétiques NON OFFICIELS fournis par l'utilisateur (`Atlas_4_plans_agricoles_test.pdf`), déclinés en
PDF, SVG, PNG couleur (150 dpi) et PNG noir & blanc (seuillage d'Otsu).

**Référence** : surface et ressources = valeurs imprimées sur chaque plan ; contour, côtés et points
d'eau = géométrie lue dans les primitives vectorielles du PDF (repère local en mètres). La surface
vectorielle est donc comparée à une valeur indépendante (le texte imprimé) ; les images sont comparées
à la géométrie vectorielle.

## Résumé

- Plans lus : **16/16**
- Vectoriel (PDF/SVG) : écart de surface max **0.00 %**, IoU min **1.0000**, position des points d'eau max **0.00 m**
- Image (PNG couleur et N&B, OCR) : écart de surface max **0.70 %**, IoU min **0.9915**, côté max **2.39 %**, position des points d'eau max **2.08 m**

## Détail

| Plan | Format | Surface (écart %) | IoU contour | Sommets | Côté max (écart %) | Points d'eau | Position eau (m, max) | Gouvernorat | Ressources lues | Échelle | Temps (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| nabeul | PDF vectoriel | +0.00 | 1.000 | 4/4 | 0.0 | 1/1 | 0.0 | ✓ | 4/4 | scale_bar | 8.6 |
| nabeul | SVG | +0.00 | 1.000 | 4/4 | 0.0 | 1/1 | 0.0 | ✓ | 4/4 | scale_bar | 6.5 |
| nabeul | PNG couleur 150 dpi | -0.00 | 0.999 | 4/4 | 0.06 | 1/1 | 0.18 | ✓ | 4/4 | printed_area | 12.4 |
| nabeul | PNG noir & blanc | -0.24 | 0.998 | 4/4 | 0.23 | 1/1 | 0.21 | ✓ | 4/4 | scale_bar_ticks | 10.2 |
| kairouan | PDF vectoriel | +0.00 | 1.000 | 6/6 | 0.0 | 1/1 | 0.0 | ✓ | 4/4 | scale_bar | 6.6 |
| kairouan | SVG | +0.00 | 1.000 | 6/6 | 0.0 | 1/1 | 0.0 | ✓ | 4/4 | scale_bar | 5.8 |
| kairouan | PNG couleur 150 dpi | +0.16 | 0.994 | 6/6 | 0.28 | 1/1 | 0.8 | ✓ | 3/4 | scale_bar_ticks | 10.7 |
| kairouan | PNG noir & blanc | -0.12 | 0.993 | 6/6 | 2.39 | 1/1 | 0.75 | ✓ | 4/4 | scale_bar_ticks | 10.4 |
| sfax | PDF vectoriel | +0.00 | 1.000 | 6/6 | 0.0 | 2/2 | 0.0 | ✓ | 4/4 | scale_bar | 6.5 |
| sfax | SVG | +0.00 | 1.000 | 6/6 | 0.0 | 2/2 | 0.0 | ✓ | 4/4 | scale_bar | 6.2 |
| sfax | PNG couleur 150 dpi | -0.52 | 0.993 | 6/6 | 0.73 | 2/2 | 1.96 | ✓ | 4/4 | scale_bar_ticks | 11.3 |
| sfax | PNG noir & blanc | -0.57 | 0.992 | 6/6 | 1.76 | 2/2 | 2.08 | ✓ | 4/4 | scale_bar_ticks | 9.6 |
| gafsa | PDF vectoriel | +0.00 | 1.000 | 7/7 | 0.0 | 1/1 | 0.0 | ✓ | 4/4 | scale_bar | 6.3 |
| gafsa | SVG | +0.00 | 1.000 | 7/7 | 0.0 | 1/1 | 0.0 | ✓ | 4/4 | scale_bar | 5.6 |
| gafsa | PNG couleur 150 dpi | -0.70 | 0.992 | 7/7 | 1.71 | 1/1 | 1.13 | ✓ | 4/4 | scale_bar_ticks | 11.4 |
| gafsa | PNG noir & blanc | -0.22 | 0.993 | 7/7 | 1.64 | 1/1 | 1.44 | ✓ | 4/4 | scale_bar_ticks | 11.3 |

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
