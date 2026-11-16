# OCP Tools

Application web en français de gestion des environnements et clusters OpenShift,
d’import de données Grafana et de stockage de pipelines GoCD.

## Démarrage local

Python 3.12+ et Docker Compose (pour Elasticsearch) sont nécessaires.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
docker compose up -d --wait
.venv/bin/python app.py
```

L’application écoute sur le **port 5002** par défaut. Le serveur Flask convient au
développement. Elasticsearch est exposé uniquement en boucle locale, sans
authentification, pour le développement. Ne pas exposer ces services directement
sur Internet : l’application ne fournit pas d’authentification utilisateur.

Variables de configuration :

| Variable | Valeur par défaut | Utilisation |
| --- | --- | --- |
| `PORT` | `5002` | Port HTTP |
| `HOST` | `0.0.0.0` | Interface d’écoute |
| `DATABASE` | `instance/ocp.sqlite` | Fichier SQLite |
| `ELASTICSEARCH_URL` | `http://localhost:9200` | Serveur Elasticsearch |
| `SECRET_KEY` | Aléatoire au démarrage | Clé de signature ; définir une valeur privée stable pour conserver les sessions et aperçus après redémarrage |

SQLite initialise son schéma automatiquement. Les données Elasticsearch restent
dans le volume Compose `elasticsearch-data`.

## Écrans

Les écrans utilisent toute la largeur disponible de la page.

- `/` : gestion des environnements et des clusters, liste des namespaces.
- `/grafana` : cadres adaptatifs par environnement et cluster ; sélectionner un CSV remplace immédiatement l’aperçu du cluster. La confirmation enregistre les données. Sans JavaScript, le bouton Prévisualiser reste utilisable.
- `/pipelines` : création et réindexation des pipelines GoCD.

## Fonctionnalités

- Création, modification et suppression des environnements et clusters.
- Types : Production, Recette, Développement. Les suppressions avec dépendances
  sont refusées pour préserver les données.
- Import simultané de plusieurs CSV pour un cluster, avec aperçu par fichier et
  confirmation avant écriture. L’aperçu signé expire après 30 minutes.
- Colonne `namespace` obligatoire, UTF-8 avec ou sans BOM, séparateurs virgule,
  point-virgule ou tabulation. Maximum 5 Mo par requête et 10 000 lignes par fichier.
- Extraction d’une séquence unique de 4 à 6 chiffres comme code application.
  Les zéros initiaux sont conservés. Un code absent ou ambigu utilise le code
  application `00000`, dans l’aperçu et lors de l’enregistrement.
- Namespaces en environnement `DEV`, uniques par cluster, regroupés par code
  application. Réimporter fusionne les doublons et actualise leur rattachement.
- Pipelines : titre et YAML validé, conservés dans SQLite et indexés dans
  `ocp-pipelines` sur Elasticsearch. L’indexation utilise un identifiant stable ;
  si Elasticsearch est indisponible, le pipeline est conservé et peut être réindexé.

Exemple CSV :

```csv
namespace,pods
app-12345-dev,3
app-6789-dev,2
```

## Vérifications

```sh
.venv/bin/python -m pytest -q
```

Les tests couvrent la gestion, les contraintes, la protection CSRF, les entrées
CSV invalides, l’extraction des codes, l’aperçu, la confirmation, les doublons,
l’échappement HTML et la reprise d’indexation. L’appel Elasticsearch est simulé
dans les tests unitaires ; le service réel est lancé séparément avec Compose.
