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


@pytest.mark.parametrize('name,expected', [('app-1234-dev', '1234'), ('app123456-dev', '123456'), ('app-1234567', None), ('app-1234-5678', None), ('no-code', None), ('app-00123', '00123')])
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
