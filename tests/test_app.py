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
