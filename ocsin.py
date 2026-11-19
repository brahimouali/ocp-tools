import csv
from datetime import date, time
import io
import json
import re
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException


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


EXCEL_SHEET = '1-OCSIN Applications'
EXCEL_COLUMNS = tuple(f'C{number}' for number in (2, 3, 4, 5, 6, 7, 8, 14, 15, 16, 17, 18, 19, 20, 21, 23, 24, 25, 28))


def excel_records(raw):
    source = io.BytesIO(raw)
    try:
        with ZipFile(source) as archive:
            if sum(entry.file_size for entry in archive.infolist()) > 32 * 1024 * 1024:
                raise ValueError('Le classeur Excel décompressé est trop volumineux.')
        workbook = load_workbook(source, read_only=True, data_only=True, keep_links=False)
        try:
            if EXCEL_SHEET not in workbook.sheetnames:
                raise ValueError(f'La feuille « {EXCEL_SHEET} » est obligatoire.')
            sheet = workbook[EXCEL_SHEET]
            sheet.reset_dimensions()
            rows = iter(sheet.rows)
            for row in rows:
                headers = [cell.value.strip() if isinstance(cell.value, str) else None for cell in row]
                if COLUMNS[CODE_COLUMN] in headers:
                    break
            else:
                raise ValueError(f'La colonne « {COLUMNS[CODE_COLUMN]} » est obligatoire.')
            positions = {}
            for column in EXCEL_COLUMNS:
                label = COLUMNS[column]
                if headers.count(label) != 1:
                    raise ValueError(f'La colonne « {label} » doit apparaître une seule fois.')
                positions[column] = headers.index(label)

            for row in rows:
                record = {}
                for column, position in positions.items():
                    if position >= len(row):
                        continue
                    cell = row[position]
                    value = cell.value
                    if isinstance(value, (date, time)):
                        value = value.isoformat()
                    if column == CODE_COLUMN and type(value) is int and re.fullmatch(r'0{4,6}', cell.number_format):
                        value = str(value).zfill(len(cell.number_format))
                    record[column] = value
                if any(value is not None and value != '' for value in record.values()):
                    yield record
        finally:
            workbook.close()
    except (BadZipFile, InvalidFileException, KeyError, OSError, ParseError) as exc:
        raise ValueError('Le classeur Excel est illisible.') from exc


# Read only the literal SELECT rows embedded in the panel. Never execute its SQL.
PANEL_SELECT = re.compile(r"\s*SELECT\s+", re.IGNORECASE)
PANEL_VALUE = re.compile(r"\s*'((?:[^']|'')*)'\s*")
PANEL_UNION = re.compile(r"UNION\s+ALL\s+", re.IGNORECASE)
PANEL_END = re.compile(r";?\s*\Z")


def panel_records(panel):
    try:
        targets = panel['targets']
        if len(targets) != 1:
            raise ValueError
        query = targets[0]['sourceQuery']['rawQuery']
        if not isinstance(query, str):
            raise ValueError
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError('Le panneau Grafana doit contenir une requête avec les lignes du rapport.') from exc

    error = 'La requête du panneau doit contenir uniquement des lignes SELECT de 28 valeurs texte, séparées par UNION ALL.'
    position = 0
    while True:
        select = PANEL_SELECT.match(query, position)
        if select is None:
            raise ValueError(error)
        position = select.end()
        row = {}
        for column in COLUMNS:
            if row:
                if query[position:position + 1] != ',':
                    raise ValueError(error)
                position += 1
            value = PANEL_VALUE.match(query, position)
            if value is None:
                raise ValueError(error)
            row[column] = value[1].replace("''", "'")
            position = value.end()
        if PANEL_END.match(query, position):
            yield row
            return
        union = PANEL_UNION.match(query, position)
        if union is None:
            raise ValueError(error)
        yield row
        position = union.end()


def parse_ocsin(raw, *, excel=False):
    if excel or raw.startswith(b'PK\x03\x04'):
        records = excel_records(raw)
    else:
        records = text_records(raw)
    return collect_applications(records)


def text_records(raw):
    try:
        content = raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('Le fichier doit être encodé en UTF-8.') from exc
    if not content.strip():
        raise ValueError('Le fichier est vide.')

    if content.lstrip().startswith(('[', '{')):
        records = json.loads(content)
        if isinstance(records, dict):
            records = panel_records(records)
    else:
        try:
            dialect = csv.Sniffer().sniff(content[:8192], delimiters=',;\t')
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(content, newline=''), dialect=dialect, strict=True)
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError('Le fichier contient des colonnes en double.')
        records = reader

    return records


def collect_applications(records):
    applications = {}
    rejected = []
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
            if key != CODE_COLUMN and value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValueError(f'Entrée {number} : valeur invalide pour « {COLUMNS[key]} ».')
            values[key] = value
        code = values.pop(CODE_COLUMN, None)
        if type(code) is int:
            code = str(code)
        normalized = code.strip() if isinstance(code, str) else None
        if not normalized or not re.fullmatch(r'(?:[0-9]{4,6}|APP-[0-9]{3,6})', normalized):
            reason = 'Code manquant' if code is None or normalized == '' else 'Format de code invalide'
            rejected.append((number, code, reason))
            continue
        code = normalized
        if code in applications:
            rejected.append((number, code, 'Code en double'))
            continue
        applications[code] = values

    if not applications and not rejected:
        raise ValueError('Le fichier ne contient aucune application.')
    return applications, rejected
