"""Auth: registration, login, tokens, profile, RBAC guards."""


def test_register_success(client):
    res = client.post("/api/auth/register", json={
        "email": "auth_ok@test.ly", "username": "auth_ok", "password": "Passw0rd!123",
    })
    assert res.status_code == 201
    body = res.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["user"]["role"] == "user"


def test_register_duplicate_email(client):
    payload = {"email": "dup@test.ly", "username": "dup1", "password": "Passw0rd!123"}
    assert client.post("/api/auth/register", json=payload).status_code == 201
    payload2 = {"email": "dup@test.ly", "username": "dup2", "password": "Passw0rd!123"}
    assert client.post("/api/auth/register", json=payload2).status_code == 409


def test_register_short_password(client):
    res = client.post("/api/auth/register", json={
        "email": "short@test.ly", "username": "shortpw", "password": "123",
    })
    assert res.status_code == 422


def test_login_success_and_me(client):
    client.post("/api/auth/register", json={
        "email": "login@test.ly", "username": "loginuser", "password": "Passw0rd!123",
    })
    res = client.post("/api/auth/login", json={
        "email": "login@test.ly", "password": "Passw0rd!123",
    })
    assert res.status_code == 200
    token = res.json()["access_token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "login@test.ly"


def test_login_wrong_password(client):
    res = client.post("/api/auth/login", json={
        "email": "login@test.ly", "password": "wrong-password",
    })
    assert res.status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_refresh_rotation(client):
    data = client.post("/api/auth/register", json={
        "email": "rot@test.ly", "username": "rot", "password": "Passw0rd!123",
    }).json()
    old_refresh = data["refresh_token"]

    res = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert res.status_code == 200
    new_tokens = res.json()
    assert new_tokens["refresh_token"] != old_refresh

    # Old refresh token must be revoked (one-time rotation)
    res2 = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert res2.status_code == 401


def test_logout_revokes_refresh(client):
    data = client.post("/api/auth/register", json={
        "email": "lo@test.ly", "username": "logoutuser", "password": "Passw0rd!123",
    }).json()
    client.post("/api/auth/logout", json={"refresh_token": data["refresh_token"]})
    res = client.post("/api/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert res.status_code == 401


def test_non_admin_cannot_access_admin(client, user_headers):
    assert client.get("/api/admin/stats", headers=user_headers).status_code == 403
