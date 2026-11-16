from contextlib import contextmanager
import csv
import io
import os
import re
import sqlite3
from pathlib import Path

import requests
import yaml
from flask import Flask, flash, redirect, render_template, request, session, url_for, jsonify, Response
import secrets
from itsdangerous import URLSafeTimedSerializer, BadSignature

SCHEMA = '''
CREATE TABLE IF NOT EXISTS environments(id INTEGER PRIMARY KEY, title TEXT NOT NULL UNIQUE, kind TEXT NOT NULL CHECK(kind IN ('Production','Recette','Développement')));
CREATE TABLE IF NOT EXISTS clusters(id INTEGER PRIMARY KEY, title TEXT NOT NULL UNIQUE, console_url TEXT NOT NULL, api_url TEXT NOT NULL, environment_id INTEGER NOT NULL REFERENCES environments(id));
CREATE TABLE IF NOT EXISTS applications(id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS namespaces(id INTEGER PRIMARY KEY, title TEXT NOT NULL, environment TEXT NOT NULL DEFAULT 'DEV', cluster_id INTEGER NOT NULL REFERENCES clusters(id), application_id INTEGER REFERENCES applications(id), UNIQUE(cluster_id,title));
CREATE TABLE IF NOT EXISTS pipelines(id INTEGER PRIMARY KEY, title TEXT NOT NULL, yaml TEXT NOT NULL, indexed INTEGER NOT NULL DEFAULT 0);
'''


def parse_csv(raw):
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('Le CSV doit être encodé en UTF-8.') from exc
    if not text.strip():
        raise ValueError('Le fichier CSV est vide.')
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames or 'namespace' not in reader.fieldnames:
        raise ValueError('La colonne « namespace » est obligatoire.')
    rows = []
    for number, row in enumerate(reader, 2):
        namespace = (row.get('namespace') or '').strip()
        if not namespace:
            raise ValueError(f'Ligne {number} : namespace vide.')
        codes = re.findall(r'(?<!\d)\d{4,6}(?!\d)', namespace)
        code = codes[0] if len(codes) == 1 else '00000'
        rows.append({'namespace': namespace, 'code': code, 'data': row})
        if len(rows) > 10000:
            raise ValueError('Maximum 10 000 lignes par fichier.')
    if not rows:
        raise ValueError('Le CSV ne contient aucune donnée.')
    return rows


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(DATABASE=os.environ.get('DATABASE', str(Path(app.instance_path) / 'ocp.sqlite')),
                      SECRET_KEY=os.environ.get('SECRET_KEY') or secrets.token_hex(32),
                      ELASTICSEARCH_URL=os.environ.get('ELASTICSEARCH_URL', 'http://localhost:9200'),
                      MAX_CONTENT_LENGTH=5 * 1024 * 1024)
    app.config.update(config or {})
    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def db():
        conn = sqlite3.connect(app.config['DATABASE'])
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    with db() as conn:
        conn.executescript(SCHEMA)

    @app.before_request
    def csrf():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_hex(32)
        if request.method == 'POST' and not secrets.compare_digest(session['csrf'], request.form.get('csrf', '')):
            return 'Jeton CSRF invalide. Rechargez la page.', 400

    @app.errorhandler(413)
    def too_large(error):
        return 'Fichier trop volumineux (maximum 5 Mo).', 413

    @app.get('/pipelines')
    @app.get('/grafana')
    @app.route('/')
    def index():
        with db() as conn:
            environments = conn.execute('SELECT * FROM environments ORDER BY title').fetchall()
            clusters = conn.execute('SELECT c.*, e.title AS environment_title FROM clusters c JOIN environments e ON e.id=c.environment_id ORDER BY c.title').fetchall()
            namespaces = conn.execute('SELECT n.*, c.title AS cluster_title, a.code FROM namespaces n JOIN clusters c ON c.id=n.cluster_id LEFT JOIN applications a ON a.id=n.application_id ORDER BY a.code,n.title').fetchall()
            pipelines = conn.execute('SELECT * FROM pipelines ORDER BY id DESC').fetchall()
        template = {'/grafana': 'grafana.html', '/pipelines': 'pipelines.html'}.get(request.path, 'index.html')
        return render_template(template, environments=environments, clusters=clusters, namespaces=namespaces, pipelines=pipelines)

    @app.get('/reports/applications-clusters')
    def application_cluster_report():
        exclude_unknown = request.args.get('exclude_unknown') == '1'
        cluster_value = request.args.get('cluster_id', '')
        try:
            selected_cluster = int(cluster_value) if cluster_value else None
        except ValueError:
            return 'Cluster invalide.', 400
        with db() as conn:
            clusters = conn.execute(
                'SELECT c.id,c.title,e.title AS environment_title FROM clusters c '
                'JOIN environments e ON e.id=c.environment_id ORDER BY e.title,c.title').fetchall()
            if selected_cluster is not None and not any(c['id'] == selected_cluster for c in clusters):
                return 'Cluster inconnu.', 400
            applications = conn.execute(
                "SELECT a.id,a.code FROM applications a "
                "WHERE (? = 0 OR a.code = '' OR ltrim(a.code, '0') != '') "
                'AND (? IS NULL OR EXISTS (SELECT 1 FROM namespaces n '
                'WHERE n.application_id=a.id AND n.cluster_id=?)) ORDER BY a.code',
                (exclude_unknown, selected_cluster, selected_cluster)).fetchall()
            if request.args.get('export') == 'csv':
                output = io.StringIO(newline='')
                writer = csv.writer(output)
                writer.writerow(['code_app'])
                writer.writerows((application['code'],) for application in applications)
                return Response(output.getvalue(), mimetype='text/csv', headers={
                    'Content-Disposition': 'attachment; filename=applications.csv'
                })
            namespaces = conn.execute(
                'SELECT application_id,cluster_id,title FROM namespaces '
                'WHERE application_id IS NOT NULL ORDER BY title').fetchall()
        presence = {}
        for namespace in namespaces:
            presence.setdefault((namespace['application_id'], namespace['cluster_id']), []).append(namespace['title'])
        return render_template('application_cluster_report.html', applications=applications,
                               clusters=clusters, presence=presence, exclude_unknown=exclude_unknown,
                               selected_cluster=selected_cluster)

    def required(name):
        value = request.form.get(name, '').strip()
        if not value:
            raise ValueError(f'Champ obligatoire : {name}')
        return value

    @app.post('/environments')
    def environment_save():
        try:
            title, kind = required('title'), required('kind')
            if kind not in ('Production', 'Recette', 'Développement'):
                raise ValueError('Type d’environnement invalide.')
            with db() as conn:
                if request.form.get('id'):
                    conn.execute('UPDATE environments SET title=?,kind=? WHERE id=?', (title, kind, request.form['id']))
                else:
                    conn.execute('INSERT INTO environments(title,kind) VALUES(?,?)', (title, kind))
            flash('Environnement enregistré.', 'success')
        except (ValueError, sqlite3.IntegrityError) as exc:
            flash(f'Enregistrement impossible : {exc}', 'error')
        return redirect(url_for('index'))

    @app.post('/clusters')
    def cluster_save():
        try:
            title, console, api, environment = [required(k) for k in ('title', 'console_url', 'api_url', 'environment_id')]
            from urllib.parse import urlparse
            for value in (console, api):
                parsed = urlparse(value)
                if parsed.scheme not in ('https', 'http') or not parsed.hostname:
                    raise ValueError('URL HTTP ou HTTPS attendue.')
            with db() as conn:
                if request.form.get('id'):
                    conn.execute('UPDATE clusters SET title=?,console_url=?,api_url=?,environment_id=? WHERE id=?', (title, console, api, environment, request.form['id']))
                else:
                    conn.execute('INSERT INTO clusters(title,console_url,api_url,environment_id) VALUES(?,?,?,?)', (title, console, api, environment))
            flash('Cluster enregistré.', 'success')
        except (ValueError, sqlite3.IntegrityError) as exc:
            flash(f'Enregistrement impossible : {exc}', 'error')
        return redirect(url_for('index'))

    @app.post('/delete/<entity>/<int:identifier>')
    def delete(entity, identifier):
        if entity not in ('environments', 'clusters'):
            return 'Entité inconnue', 404
        try:
            with db() as conn:
                conn.execute(f'DELETE FROM {entity} WHERE id=?', (identifier,))
            flash('Suppression effectuée.', 'success')
        except sqlite3.IntegrityError:
            flash('Suppression impossible : des éléments dépendent de cette entrée.', 'error')
        return redirect(url_for('index'))

    @app.post('/import')
    def import_csv():
        try:
            cluster = required('cluster_id')
            with db() as conn:
                if not conn.execute('SELECT id FROM clusters WHERE id=?', (cluster,)).fetchone():
                    raise ValueError('Cluster inconnu.')
            files = request.files.getlist('files')
            signer = URLSafeTimedSerializer(app.secret_key, salt='csv-preview')
            token = request.form.get('preview')
            if token:
                try:
                    payload = signer.loads(token, max_age=1800)
                except BadSignature as exc:
                    raise ValueError('Aperçu expiré ou invalide. Rechargez le CSV.') from exc
                if str(payload['cluster']) != cluster:
                    raise ValueError('Cluster modifié depuis l’aperçu.')
                previews = payload['previews']
            if not token and (not files or not any(f.filename for f in files)):
                raise ValueError('Choisissez au moins un fichier CSV.')
            if not token:
                previews = [{'filename': f.filename, 'rows': parse_csv(f.read())} for f in files if f.filename]
            if request.form.get('confirm') == 'yes':
                with db() as conn:
                    for preview in previews:
                        for row in preview['rows']:
                            code = row['code'] or '00000'
                            conn.execute('INSERT OR IGNORE INTO applications(code) VALUES(?)', (code,))
                            application_id = conn.execute('SELECT id FROM applications WHERE code=?', (code,)).fetchone()['id']
                            conn.execute('INSERT INTO namespaces(title,cluster_id,application_id) VALUES(?,?,?) ON CONFLICT(cluster_id,title) DO UPDATE SET application_id=excluded.application_id', (row['namespace'], cluster, application_id))
                flash('Import terminé. Les doublons ont été fusionnés.', 'success')
                return redirect('/grafana')
            context = dict(previews=previews, cluster_id=cluster, preview_token=signer.dumps({'cluster': cluster, 'previews': previews}))
            if request.headers.get('X-Requested-With') == 'fetch':
                return jsonify(html=render_template('preview_content.html', **context))
            return render_template('preview.html', **context)
        except (ValueError, csv.Error, sqlite3.IntegrityError) as exc:
            if request.headers.get('X-Requested-With') == 'fetch':
                return jsonify(error=f'Import impossible : {exc}'), 400
            flash(f'Import impossible : {exc}', 'error')
            return redirect('/grafana')

    @app.post('/pipelines')
    def pipeline_save():
        try:
            title, content = required('title'), required('yaml')
            if not isinstance(yaml.safe_load(content), dict):
                raise ValueError('Le YAML doit contenir un objet.')
            with db() as conn:
                identifier = conn.execute('INSERT INTO pipelines(title,yaml) VALUES(?,?)', (title, content)).lastrowid
            return index_pipeline(identifier)
        except (ValueError, yaml.YAMLError) as exc:
            flash(f'Pipeline invalide : {exc}', 'error')
            return redirect('/pipelines')

    @app.post('/pipelines/<int:identifier>/index')
    def index_pipeline(identifier):
        with db() as conn:
            pipeline = conn.execute('SELECT * FROM pipelines WHERE id=?', (identifier,)).fetchone()
        if pipeline is None:
            return 'Pipeline inconnu', 404
        try:
            response = requests.put(app.config['ELASTICSEARCH_URL'].rstrip('/') + f'/ocp-pipelines/_doc/{identifier}', json={'title': pipeline['title'], 'yaml': pipeline['yaml']}, timeout=10)
            response.raise_for_status()
            with db() as conn:
                conn.execute('UPDATE pipelines SET indexed=1 WHERE id=?', (identifier,))
            flash('Pipeline enregistré et indexé dans Elasticsearch.', 'success')
        except requests.RequestException:
            flash('Pipeline conservé dans SQLite. Elasticsearch est indisponible : réessayez l’indexation.', 'error')
        return redirect('/pipelines')

    return app


if __name__ == '__main__':
    create_app().run(host=os.environ.get('HOST', '0.0.0.0'), port=int(os.environ.get('PORT', '5002')))
