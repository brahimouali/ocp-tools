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

## Gestion des environnements
Un écran permet de gérer les environnements et les clusters.

## Import des données Grafana
Un écran propose d'importer pour chaque cluster un fichier CSV.
Dans chaque fichier CSV, la colonne "namespace" permet d'alimenter les entités Namespace.
Dans le nom du namespace, il y a un code entre 4 et 6 chiffres représentant le code application de l'application.
Pour chaque fichier déposé dans l'interface, un tableau permet de visualiser les données lues et voir le code application et le nom du namespace.