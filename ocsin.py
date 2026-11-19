import csv
import io
import json
import re


# Grafana's organize transformation maps the source aliases to these labels.
COLUMNS = {
    'C1': 'AssetLifecycleStatus',
    'C2': "Application ID de l'EC",
    'C3': 'Application Nom',
    'C4': 'Application Statut',
    'C5': "Application Date d'installation",
    'C6': 'Application Catégorie 1',
    'C7': 'Application Catégorie 2',
    'C8': 'Application Catégorie 3',
    'C9': 'Application Nom du produit',
    'C10': 'Application Modèle/Version',
    'C11': 'Application Fabricant',
    'C12': 'Application Nom du fournisseur',
    'C13': 'Application Accès par compte auto-généré',
    'C14': 'Application Acronyme',
    'C15': "Application Type d'application",
    'C16': 'Application Priorité en termes de disponibilité',
    'C17': 'Application Priorité en termes de confidentialité',
    'C18': 'Application Environnement poste de travail',
    'C19': 'Application Classification des informations',
    'C20': 'Application Informations supplémentaires',
    'C21': "Application Dossier d'assistance",
    'C22': "Application Moyen d'accès soumis à licence",
    'C23': 'Application Priorité globale',
    'C24': 'Application Description EC',
    'C25': "Application Type de moyen d'accès",
    'C26': 'Application Volume actuel',
    'C27': 'Application Volume futur',
    'C28': 'Application Utilisateurs concernés',
}
CODE_COLUMN = 'C2'
ATTRIBUTES = {key: label for key, label in COLUMNS.items() if key != CODE_COLUMN}
COLUMN_KEYS = {**{key: key for key in COLUMNS}, **{label: key for key, label in COLUMNS.items()}}


def parse_ocsin(raw):
    try:
        content = raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('Le fichier doit être encodé en UTF-8.') from exc
    if not content.strip():
        raise ValueError('Le fichier est vide.')

    if content.lstrip().startswith(('[', '{')):
        records = json.loads(content)
        if not isinstance(records, list):
            raise ValueError('Le JSON doit contenir une liste de lignes. Une configuration de panneau Grafana ne contient pas les données du rapport.')
    else:
        try:
            dialect = csv.Sniffer().sniff(content[:8192], delimiters=',;\t')
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(content, newline=''), dialect=dialect, strict=True)
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError('Le fichier contient des colonnes en double.')
        records = reader

    applications = {}
    for number, row in enumerate(records, 1):
        if number > 10000:
            raise ValueError('Maximum 10 000 lignes par fichier.')
        if not isinstance(row, dict) or None in row:
            raise ValueError(f'Entrée {number} : ligne invalide.')
        values = {}
        for column, value in row.items():
            key = COLUMN_KEYS.get(column.strip())
            if key is None:
                continue
            if key in values:
                raise ValueError(f'Entrée {number} : colonne « {COLUMNS[key]} » en double.')
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValueError(f'Entrée {number} : valeur invalide pour « {COLUMNS[key]} ».')
            values[key] = value
        code = values.pop(CODE_COLUMN, None)
        if type(code) is int:
            code = str(code)
        if not isinstance(code, str) or not re.fullmatch(r'[0-9]{4,6}', code.strip()):
            raise ValueError(f'Entrée {number} : « {COLUMNS[CODE_COLUMN]} » doit contenir un code de 4 à 6 chiffres.')
        code = code.strip()
        if code in applications:
            raise ValueError(f'Entrée {number} : code application {code} en double.')
        applications[code] = values

    if not applications:
        raise ValueError('Le fichier ne contient aucune application.')
    return applications
