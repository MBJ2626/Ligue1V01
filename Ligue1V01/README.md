# Tunisia MatchSheet DB

Prototype web local pour uploader des feuilles de match de football tunisien, extraire les données, les revoir puis les insérer dans une base SQLite exploitable.

## Fonctionnalités

- Upload de fichiers `.pdf`, `.docx`, `.xlsx`, `.xlsm`, `.xls`, `.csv`.
- Extraction de texte depuis PDF texte, Word DOCX, Excel et CSV.
- Extraction spécialisée des PDF officiels FTF `FEUILLE DE MATCH INFORMATISÉE`.
- Détection d'un PDF contenant plusieurs matchs : un seul PDF peut créer plusieurs matchs en base.
- Brouillon JSON modifiable avant insertion.
- Base SQLite avec matchs, clubs, joueurs, staff, officiels, événements, observations.
- Événements structurés : buts, cartons jaunes, cartons rouges, remplacements, blessés si présents.
- Pages web : dashboard, documents, matchs, détail match, joueurs, événements, arbitres.
- Exports CSV depuis l'interface.
- Notes et observations ajoutables après validation d'un match.

## Amélioration ajoutée pour les feuilles FTF Ligue 1

Le fichier `app/ftf_parser.py` ajoute un parser dédié au format observé dans les feuilles officielles FTF :

- segmentation automatique par page de début `FEUILLE DE MATCH INFORMATISÉE` ;
- regroupement des pages d'un même match ;
- lecture des deux colonnes titulaires/remplaçants avec association domicile/extérieur ;
- extraction des deux colonnes de staff ;
- extraction des remplacements ;
- extraction des officiels du match ;
- extraction des joueurs avertis, expulsés et blessés ;
- extraction des buts depuis le bloc supérieur du PDF lorsque l'icône de but est perdue par l'extraction texte ;
- mapping automatique des codes clubs, par exemple `EST`, `CSS`, `ASR`, vers les vrais clubs du match ;
- contrôles simples : 11 titulaires par équipe et cohérence entre score final et nombre de buts extraits.

## Installation locale

```bash
cd tunisia_matchsheet_site
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Sur Windows PowerShell :

```powershell
cd tunisia_matchsheet_site
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Ouvre ensuite :

```text
http://127.0.0.1:8000
```

## Test rapide

Des fichiers d'exemple sont dans le dossier `examples/` :

- `sample_match_sheet.docx`
- `sample_match_sheet.xlsx`
- `sample_match_sheet.pdf`

Va dans `Upload`, envoie un fichier, vérifie le JSON, puis clique sur `Insérer dans la base`.

Avec un PDF officiel FTF contenant plusieurs feuilles de match, la page de revue indique `PDF multi-match`, le nombre de matchs détectés et un tableau de prévisualisation. La validation insère tous les matchs détectés.


## Analyse en ligne de commande

Tu peux tester l'extraction sans lancer le serveur :

```bash
python tools/analyze_file.py /chemin/vers/feuille.pdf --json-out sortie.json
```

La commande affiche le nombre de matchs détectés, les scores, joueurs, buts, cartons et remplacements.

## Structure

```text
app/
  main.py          routes FastAPI
  database.py      schéma SQLite + requêtes + insertion single/batch
  extractor.py     lecture PDF / DOCX / Excel / CSV
  parser.py        parser générique + routage vers parser FTF
  ftf_parser.py    parser dédié aux feuilles officielles FTF
  templates/       pages HTML Jinja
  static/          CSS + JS
  uploads/         fichiers uploadés
  data/            base SQLite + exports
examples/          fichiers de test
```

## Limites connues

- Les PDF scannés nécessitent un vrai OCR. Le prototype les détecte mais ne peut pas lire automatiquement une image sans OCR.
- Les icônes de but/carton ne sont pas toujours conservées dans le texte PDF. Le parser FTF compense en croisant le bloc supérieur avec les tableaux `JOUEURS AVERTIS` et `JOUEURS EXPULSÉS`.
- Les feuilles officielles peuvent évoluer. Si la FTF change la mise en page, il faudra enrichir `app/ftf_parser.py`.
- Le format Word ancien `.doc` doit idéalement être converti en `.docx` ou PDF texte.

## Prochaine évolution recommandée

- Ajouter un moteur OCR : Tesseract, PaddleOCR, Google Vision ou Azure Document Intelligence.
- Ajouter authentification et rôles : admin, analyste, lecteur.
- Remplacer SQLite par PostgreSQL pour un déploiement multi-utilisateurs.
- Ajouter une couche LLM multimodale pour transformer les feuilles complexes en JSON avec score de confiance par champ.
- Ajouter validation avancée : joueurs sortis, rouges, suspensions, minute de but après remplacement, homonymes, licences incohérentes.

## Notifications discipline

Le site contient maintenant un onglet **Notifications** (`/notifications`). Il calcule automatiquement les alertes à partir des événements de type carton stockés en base.

Règles MVP :

- **Carton rouge** : notification critique immédiate pour vérifier la suspension du joueur.
- **3 cartons jaunes sur une période donnée** : notification critique indiquant un risque de suspension automatique au match suivant.
- **2 cartons jaunes sur la période** : pré-alerte de surveillance, activable/désactivable depuis la page.

Par défaut, la page utilise :

```text
Période : 10 matchs du club
Seuil : 3 cartons jaunes
```

Ces paramètres sont modifiables depuis l'interface :

```text
http://127.0.0.1:8000/notifications?period=10&threshold=3&include_watch=1
```

Une API JSON est aussi disponible :

```text
http://127.0.0.1:8000/api/notifications
```

Important : le système signale les risques automatiquement, mais la décision finale doit être vérifiée avec les règlements et décisions officielles de la compétition.


## Saisie manuelle sans fichier

La version avec notifications contient aussi l'onglet **Saisie manuelle** (`/manual`). Il permet de créer un match sans PDF, Word ou Excel :

- informations du match : compétition, saison, journée, date, heure, stade, score ;
- joueurs domicile et extérieur ;
- staff des deux équipes ;
- officiels/arbitres ;
- buts ;
- cartons jaunes et rouges ;
- remplacements ;
- observations et notes.

Les listes utilisent un format simple : une ligne par élément, avec les champs séparés par `;`.

Exemples :

```text
# Joueurs
1; JOUEUR NOM; 990101001; titulaire; oui; oui; Gardien; TN;
10; JOUEUR NOM; 990101002; remplaçant;;;;;

# Cartons
58; home; JOUEUR NOM; jaune; contestation
82; away; JOUEUR NOM; rouge; faute grossière

# Remplacements
65; home; JOUEUR ENTRANT; JOUEUR SORTANT;
```

Après validation, le match est inséré directement dans la base et devient visible dans les onglets Matchs, Joueurs, Événements, Arbitres et Notifications.
