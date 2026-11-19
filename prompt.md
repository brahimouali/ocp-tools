# Base de données
Base de données SQLite pour le stockage des données.
Index ElasticSearch pour le stockage des fichier YAML.

# Entités

## Environnement
- Titre
- Type (Production | Recette | Développement)

## Cluster OpenShift
- Titre
- URL Console
- URL API
- Environnement

## Namespace
- Titre
- Environnement (DEV)
- Cluster OpenShift

## Application
- Code application
- Liste des namespaces

# Pipeline GoCD
- Titre
- Code YAML

# Ecrans
Chaque écran est une entrée du menu principal.
Toute la largeur de la page est utilisée.

## Gestion des environnements
Un écran permet de gérer les environnements et les clusters.

## Import des données Grafana
Un écran propose de gérer l'importation de fichiers CSV pour alimenter les namespaces.
L'écran 
- affiche un cadre pour chaque environnement
- et dans le cadre pour l'environnement un sous cadre pour chaque cluster
- un bouton d'import de fichier CSV
- un tableau affichant les éléments tirés du CSV
Les cadres d'environnement sont affichés de façon horizontale et s'adaptent à la largeur de la page.
Les sous cadres sont aussi affichés de façon horizontale et s'adaptent à la largeur du cadre.
A chaque fois qu'un fichier CSV est choisi,
- la tableau est remplacé par les informations tirés du fichier CSV
- le tableau affiche :
  - le nom du namespace
  - le code application du namespace contenu dans le nom (code entre 4 et 6 chiffres représentant le code application de l'application)
  - si le code application n'est pas reconnu, alors le code 00000 est utilisé

## Import du rapport grafana "OCSIN Applications"
A partir du fichier d'exemple de données : prompt-extras/ocsin-applications-anonymized.json, rajoute les colonnes de ce fichier comme des attributs d'une application dans une nouvelle entité liée à l'entité application. Réalise aussi un écran d'importation des données.

## Rapport application/cluster
Cet écran propose un tableau qui liste toutes les applications et pour chaque cluster met une icone:
- une icone validation verte indique que l'application a un namespace dans ce cluster et au survol de l'icone, une liste des namespaces apparaît en popup
- une icone absence rouge indique que l'application n'a pas de namespace dans ce cluster
Un filtre permet d'exclure les applications dont le code ne contient que des 0.
Un filtre par cluster permet de filtrer les applications par cluster.
Un bouton d'export permet de générer un fichier csv avec 1 seule colonne :
- code_app et en valeur les codes applications affichés (filtrés)
Le tableau affiche les attributs issues de l'entité issue de l'import "OCSIN Applications".