from app.services.activation_service import create_activation_code
import app.main as main_module


def setup_function():
    main_module.ENFORCE_ACTIVATION = True


def teardown_function():
    main_module.ENFORCE_ACTIVATION = False


def test_business_api_requires_activation(client):
    client.headers.pop("Authorization", None)
    resp = client.get("/api/projects")
    assert resp.status_code == 401


def test_activate_7_day_code_allows_business_api(client, db):
    client.headers.pop("Authorization", None)
    code = create_activation_code(db, days=7, note="test")
    resp = client.post("/api/auth/trial/activate", json={"code": code, "requested_days": 7})
    assert resp.status_code == 200
    body = resp.json()
    assert body["trial"]["trial_days"] == 7

    client.headers.update({"Authorization": f"Bearer {body['access_token']}"})
    assert client.get("/api/projects").status_code == 200


def test_activate_rejects_wrong_trial_days(client, db):
    client.headers.pop("Authorization", None)
    code = create_activation_code(db, days=14, note="test")
    resp = client.post("/api/auth/trial/activate", json={"code": code, "requested_days": 7})
    assert resp.status_code == 400


def test_activate_rejects_reused_code(client, db):
    client.headers.pop("Authorization", None)
    code = create_activation_code(db, days=14, note="test")
    first = client.post("/api/auth/trial/activate", json={"code": code, "requested_days": 14})
    assert first.status_code == 200
    second = client.post("/api/auth/trial/activate", json={"code": code, "requested_days": 14})
    assert second.status_code == 400
