"""Run only through t2_checks.py regression: original env/startup are suppressed."""
from fastapi.testclient import TestClient


def test_existing_health_and_disabled_gis_are_separate():
    import main
    with TestClient(main.app) as client:
        assert client.get('/health').json()=={'ok':True}
        assert client.get('/gis/me',headers={'X-Admin-Token':'dummy-legacy-header'}).status_code==503


def test_existing_cors_adds_only_idempotency_header():
    import main
    with TestClient(main.app) as client:
        response=client.options('/gis/datasets',headers={'Origin':'http://localhost:3000',
            'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'Authorization,Content-Type,Idempotency-Key'})
        assert response.status_code==200
        assert response.headers['access-control-allow-origin']=='http://localhost:3000'
        assert 'idempotency-key' in response.headers['access-control-allow-headers'].lower()
        blocked=client.options('/gis/datasets',headers={'Origin':'https://unknown.invalid','Access-Control-Request-Method':'POST'})
        assert 'access-control-allow-origin' not in blocked.headers


def test_legacy_mount_gis_body_error_is_inside_cors():
    import main
    with TestClient(main.app) as client:
        response=client.post('/gis/datasets',content=b'x'*65537,
            headers={'Origin':'http://localhost:3000','Content-Type':'application/json'})
        assert response.status_code==422
        assert response.headers['access-control-allow-origin']=='http://localhost:3000'
