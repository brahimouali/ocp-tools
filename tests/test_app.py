import io
import re
import sqlite3
from unittest.mock import Mock

import pytest
import requests
from app import create_app, parse_csv


@pytest.fixture
def client(tmp_path):
    app = create_app({'TESTING': True, 'DATABASE': str(tmp_path / 'test.sqlite'), 'SECRET_KEY': 'test-only'})
    with app.test_client() as client:
        client.get('/')
        yield client


def post(client, path, data=None):
    with client.session_transaction() as session:
        token = session['csrf']
    return client.post(path, data={**(data or {}), 'csrf': token}, follow_redirects=True)


def seed(client):
    post(client, '/environments', {'title': 'Dev', 'kind': 'Développement'})
    post(client, '/clusters', {'title': 'Cluster A', 'console_url': 'https://console.example.org', 'api_url': 'https://api.example.org:6443', 'environment_id': '1'})


def test_management(client):
    seed(client)
    assert b'Cluster A' in client.get('/').data
    assert 'Développement' in client.get('/').text
    post(client, '/environments', {'id': '1', 'title': 'Recette', 'kind': 'Recette'})
    assert 'Recette' in client.get('/').text
    assert 'dépendent' in post(client, '/delete/environments/1').text
    post(client, '/delete/clusters/1')
    post(client, '/delete/environments/1')
    assert 'Aucun environnement' in client.get('/').text


def test_validation_csrf_and_urls(client):
    assert client.post('/environments', data={'title': 'invalid'}).status_code == 400
    post(client, '/environments', {'title': 'Dev', 'kind': 'invalid'})
    assert 'Aucun environnement' in client.get('/').text
    seed(client)
    assert 'URL HTTP' in post(client, '/clusters', {'title': 'Bad', 'console_url': 'javascript:alert(1)', 'api_url': 'https://api.test', 'environment_id': '1'}).text


@pytest.mark.parametrize('name,expected', [('app-1234-dev', '1234'), ('app123456-dev', '123456'), ('app-1234567', '00000'), ('app-1234-5678', '00000'), ('no-code', '00000'), ('app-00123', '00123')])
def test_codes(name, expected):
    assert parse_csv(f'namespace\n{name}\n'.encode())[0]['code'] == expected


@pytest.mark.parametrize('raw', [b'', b'other\na\n', b'namespace,other\n,x\n', b'namespace\n', b'namespace\n\xff'])
def test_bad_csv(raw):
    with pytest.raises(ValueError):
        parse_csv(raw)


def test_import_preview_confirmation_and_idempotency(client):
    seed(client)
    response = post(client, '/import', {'cluster_id': '1', 'files': [(io.BytesIO(b'\xef\xbb\xbfnamespace;count\napp-12345-dev;2\n'), 'grafana.csv'), (io.BytesIO(b'namespace\napp-12345-other\n'), 'other.csv')]})
    assert 'grafana.csv' in response.text and 'other.csv' in response.text
    assert '12345' in response.text
    assert 'Aucun namespace' in client.get('/').text
    token = re.search(r'name="preview" value="([^"]+)"', response.text).group(1)
    for _ in range(2):
        assert 'Import terminé' in post(client, '/import', {'cluster_id': '1', 'preview': token, 'confirm': 'yes'}).text
    with sqlite3.connect(client.application.config['DATABASE']) as db:
        assert db.execute('SELECT count(*) FROM namespaces').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM applications').fetchone()[0] == 1
    assert 'invalide' in post(client, '/import', {'cluster_id': '1', 'preview': token + 'x', 'confirm': 'yes'}).text


def test_pipeline_index_and_retry(client, monkeypatch):
    put = Mock(side_effect=requests.ConnectionError())
    monkeypatch.setattr('app.requests.put', put)
    assert 'Elasticsearch est indisponible' in post(client, '/pipelines', {'title': 'Build', 'yaml': 'pipelines:\n  build: {}'}).text
    put.side_effect = None
    put.return_value = Mock()
    assert 'indexé dans Elasticsearch' in post(client, '/pipelines/1/index').text
    assert put.call_args.kwargs['json']['yaml'] == 'pipelines:\n  build: {}'
    assert 'Pipeline invalide' in post(client, '/pipelines', {'title': 'Bad', 'yaml': '[invalid'}).text


def test_xss_escaped(client):
    post(client, '/environments', {'title': '<script>alert(1)</script>', 'kind': 'Production'})
    assert '<script>' not in client.get('/').text


def test_separate_screens_and_cluster_cards(client):
    seed(client)
    post(client, '/environments', {'title': 'Prod', 'kind': 'Production'})
    post(client, '/clusters', {'title': 'Cluster B', 'console_url': 'https://b.example.org', 'api_url': 'https://b.example.org', 'environment_id': '2'})
    home = client.get('/').text
    grafana = client.get('/grafana').text
    pipelines = client.get('/pipelines').text
    assert 'name="console_url"' in home
    assert 'class="csv-import"' not in home
    assert grafana.count('class="environment-card"') == 2
    assert grafana.count('class="cluster-card"') == 2
    assert 'value="1"' in grafana and 'value="2"' in grafana
    assert 'grafana.js' in grafana
    assert 'name="yaml"' not in grafana
    assert 'name="yaml"' in pipelines
    assert 'name="console_url"' not in pipelines
    assert 'aria-current="page"' in grafana


def test_inline_preview_replaces_data_without_saving(client):
    seed(client)
    with client.session_transaction() as session:
        csrf = session['csrf']
    def preview(raw):
        return client.post('/import', data={
            'csrf': csrf, 'cluster_id': '1',
            'files': (io.BytesIO(raw), 'grafana.csv')
        }, headers={'X-Requested-With': 'fetch'})
    first = preview(b'namespace\napp-00123-dev\n')
    assert first.status_code == 200
    assert '00123' in first.json['html']
    second = preview(b'namespace\napp-9876-dev\n')
    assert '9876' in second.json['html']
    assert '00123' not in second.json['html']
    assert 'Aucun namespace' in client.get('/').text
    invalid = preview(b'wrong\nvalue\n')
    assert invalid.status_code == 400
    assert 'namespace' in invalid.json['error']
    escaped = preview(b'namespace\n<script>alert(1)</script>-1234\n')
    assert '<script>' not in escaped.json['html']
    token = re.search(r'name="preview" value="([^"]+)"', second.json['html']).group(1)
    result = post(client, '/import', {'cluster_id': '1', 'preview': token, 'confirm': 'yes'})
    assert result.request.path == '/grafana'
    assert 'app-9876-dev' in result.text


def test_unknown_codes_preview_and_persistence(client):
    seed(client)
    response = post(client, '/import', {
        'cluster_id': '1',
        'files': (io.BytesIO(b'namespace\nno-code\napp-1234-5678\napp-00123-dev\n'), 'codes.csv')
    })
    assert response.text.count('<td>00000</td>') == 2
    assert '<td>00123</td>' in response.text
    token = re.search(r'name="preview" value="([^"]+)"', response.text).group(1)
    for _ in range(2):
        result = post(client, '/import', {'cluster_id': '1', 'preview': token, 'confirm': 'yes'})
        assert result.text.count('<td>00000</td>') == 2
    with sqlite3.connect(client.application.config['DATABASE']) as db:
        rows = db.execute('SELECT n.title,a.code FROM namespaces n JOIN applications a ON n.application_id=a.id ORDER BY n.title').fetchall()
        assert rows == [('app-00123-dev', '00123'), ('app-1234-5678', '00000'), ('no-code', '00000')]
        assert db.execute('SELECT count(*) FROM applications WHERE code=?', ('00000',)).fetchone()[0] == 1


def test_application_cluster_report_matrix_and_filter(client):
    seed(client)
    post(client, '/clusters', {'title': 'Cluster B', 'console_url': 'https://b.example.org', 'api_url': 'https://b.example.org', 'environment_id': '1'})
    with sqlite3.connect(client.application.config['DATABASE']) as db:
        db.executemany('INSERT INTO applications(id,code) VALUES(?,?)', [(1, '00123'), (2, '00000'), (3, '9999')])
        db.executemany('INSERT INTO namespaces(title,cluster_id,application_id) VALUES(?,?,?)', [
            ('app-00123-dev', 1, 1), ('app-00123-extra', 1, 1),
            ('<script>alert(1)</script>', 2, 1), ('unknown', 2, 2)])
    page = client.get('/reports/applications-clusters')
    assert page.status_code == 200
    html = page.text
    assert 'Cluster A' in html and 'Cluster B' in html
    assert html.count('class="presence-status present"') == 3
    assert html.count('class="presence-status absent"') == 3
    assert 'app-00123-dev' in html and 'app-00123-extra' in html
    assert '&lt;script&gt;' in html and '<script>alert(1)</script>' not in html
    assert 'data-application="9999"' in html  # applications without namespaces are retained
    filtered = client.get('/reports/applications-clusters?exclude_unknown=1').text
    assert 'data-application="00000"' not in filtered
    assert 'data-application="00123"' in filtered
    assert filtered.count('class="presence-status present"') == 2
    assert filtered.count('class="presence-status absent"') == 2
    assert 'name="exclude_unknown" value="1" checked' in filtered
    assert 'data-application="00000"' in client.get('/reports/applications-clusters?exclude_unknown=0').text
    assert '/reports/applications-clusters' in client.get('/').text


def test_application_cluster_report_empty_states(client):
    html = client.get('/reports/applications-clusters').text
    assert 'Aucun cluster.' in html and 'Aucune application.' in html
    with sqlite3.connect(client.application.config['DATABASE']) as db:
        db.execute('INSERT INTO applications(code) VALUES(?)', ('00000',))
    html = client.get('/reports/applications-clusters?exclude_unknown=1').text
    assert 'Aucune application correspondant au filtre.' in html


@pytest.mark.parametrize('exclude_unknown', [False, True])
def test_report_zero_only_filter_and_csv_match_display(client, exclude_unknown):
    import csv
    codes = ['0000', '00000', '000000', '0001', '00123', '1000', '999999']
    with sqlite3.connect(client.application.config['DATABASE']) as db:
        db.executemany('INSERT INTO applications(code) VALUES(?)', [(code,) for code in codes])
    query = {'exclude_unknown': '1'} if exclude_unknown else {}
    page = client.get('/reports/applications-clusters', query_string=query)
    displayed = re.findall(r'data-application="([^"]+)"', page.text)
    expected = sorted(code for code in codes if not exclude_unknown or set(code) != {'0'})
    assert displayed == expected
    exported = client.get('/reports/applications-clusters', query_string={**query, 'export': 'csv'})
    assert exported.status_code == 200
    assert exported.mimetype == 'text/csv'
    assert 'attachment; filename=applications.csv' == exported.headers['Content-Disposition']
    rows = list(csv.reader(io.StringIO(exported.text)))
    assert rows == [['code_app']] + [[code] for code in displayed]
    assert '00123' in exported.text


def test_report_csv_empty_result_has_header_only(client):
    import csv
    with sqlite3.connect(client.application.config['DATABASE']) as db:
        db.execute('INSERT INTO applications(code) VALUES(?)', ('000000',))
    response = client.get('/reports/applications-clusters?exclude_unknown=1&export=csv')
    assert list(csv.reader(io.StringIO(response.text))) == [['code_app']]


@pytest.mark.parametrize('cluster_id,exclude_unknown,expected', [
    ('1', False, ['00000', '00123']), ('1', True, ['00123']),
    ('2', False, ['00123', '9876']), ('2', True, ['00123', '9876']),
    ('3', False, []), ('', False, ['00000', '00123', '9876', '9999']),
])
def test_report_cluster_filter_and_export(client, cluster_id, exclude_unknown, expected):
    import csv
    seed(client)
    for title in ['Cluster B', 'Cluster vide']:
        post(client, '/clusters', {'title': title, 'console_url': 'https://example.org', 'api_url': 'https://example.org', 'environment_id': '1'})
    with sqlite3.connect(client.application.config['DATABASE']) as db:
        db.executemany('INSERT INTO applications(id,code) VALUES(?,?)', [(1, '00000'), (2, '00123'), (3, '9876'), (4, '9999')])
        db.executemany('INSERT INTO namespaces(title,cluster_id,application_id) VALUES(?,?,?)', [
            ('unknown', 1, 1), ('app-00123-dev', 1, 2), ('app-00123-extra', 1, 2),
            ('app-00123-b', 2, 2), ('app-9876', 2, 3)])
    query = {'cluster_id': cluster_id, 'exclude_unknown': '1' if exclude_unknown else '0'}
    page = client.get('/reports/applications-clusters', query_string=query)
    assert page.status_code == 200
    assert re.findall(r'data-application="([^"]+)"', page.text) == expected
    assert 'Cluster A' in page.text and 'Cluster B' in page.text  # keep comparison columns
    if cluster_id:
        assert f'value="{cluster_id}" selected' in page.text
        assert f'name="cluster_id" value="{cluster_id}"' in page.text
    response = client.get('/reports/applications-clusters', query_string={**query, 'export': 'csv'})
    assert list(csv.reader(io.StringIO(response.text))) == [['code_app']] + [[code] for code in expected]
    if not expected:
        assert 'Aucune application correspondant au filtre.' in page.text


@pytest.mark.parametrize('cluster_id', ['invalid', '999999', '-1', '0', '1 OR 1=1'])
def test_report_rejects_invalid_cluster_filter(client, cluster_id):
    for export in ['', 'csv']:
        response = client.get('/reports/applications-clusters', query_string={'cluster_id': cluster_id, 'export': export})
        assert response.status_code == 400
        assert 'Cluster' in response.text


def test_ocsin_import_updates_report_and_keeps_csv_codes_only(client):
    seed(client)
    preview = post(client, '/import', {
        'cluster_id': '1', 'files': (io.BytesIO(b'namespace\napp-01234-dev\n'), 'namespaces.csv'),
    })
    token = re.search(r'name="preview" value="([^"]+)"', preview.text).group(1)
    post(client, '/import', {'cluster_id': '1', 'preview': token, 'confirm': 'yes'})

    assert b'Import OCSIN Applications' in client.get('/grafana/ocsin-applications').data
    imported = post(client, '/grafana/ocsin-applications', {
        'file': (io.BytesIO(
            "Application ID de l'EC;Application Nom;C28\n01234;Mon <application>;Équipe\n"
            "98765;Application hors cluster;\n".encode()
        ), 'ocsin.csv'),
    })
    assert 'Import OCSIN terminé : 2' in imported.text
    report = client.get('/reports/applications-clusters?cluster_id=1').text
    assert 'Mon &lt;application&gt;' in report
    assert 'Équipe' in report
    assert 'app-01234-dev' in report
    assert 'Application hors cluster' not in report
    assert 'Application hors cluster' in client.get('/reports/applications-clusters').text
    assert client.get('/reports/applications-clusters?cluster_id=1&export=csv').text.splitlines() == [
        'code_app', '01234',
    ]

    post(client, '/grafana/ocsin-applications', {
        'file': (io.BytesIO(b'[{"C2":"01234","C3":"Nom actualise"}]'), 'ocsin.json'),
    })
    report = client.get('/reports/applications-clusters?cluster_id=1').text
    assert 'Nom actualise' in report
    assert 'Mon &lt;application&gt;' not in report
    assert 'app-01234-dev' in report


def test_ocsin_import_rejects_invalid_file_atomically(client):
    response = post(client, '/grafana/ocsin-applications', {
        'file': (io.BytesIO(b'[{"C2":"12345","C3":"Valide"},{"C2":"invalide"}]'), 'ocsin.json'),
    })
    assert 'Import OCSIN impossible' in response.text
    assert '12345' not in client.get('/reports/applications-clusters?export=csv').text
