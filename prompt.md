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
