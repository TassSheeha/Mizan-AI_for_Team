"""Admin API: RBAC, stats, users, notifications, documents, health, backup, rate limits."""


def test_admin_endpoints_require_admin(client, user_headers):
    for path in ["/api/admin/stats", "/api/admin/users", "/api/admin/documents",
                 "/api/admin/health", "/api/admin/feedback", "/api/admin/audit-log"]:
        assert client.get(path, headers=user_headers).status_code == 403
    assert client.get(path, headers={}).status_code == 401


def test_stats_shape(client, admin_headers):
    res = client.get("/api/admin/stats", headers=admin_headers)
    assert res.status_code == 200
    body = res.json()
    for key in ["users", "conversations", "messages", "documents", "indexed_chunks",
                "ai_status", "feedback", "avg_confidence"]:
        assert key in body


def test_users_list_and_self_lockout_protection(client, admin_headers):
    users = client.get("/api/admin/users", headers=admin_headers).json()
    assert len(users) >= 1
    admin_user = next(u for u in users if u["role"] == "admin")

    # Admin cannot deactivate or demote themselves
    res = client.patch(
        f"/api/admin/users/{admin_user['id']}",
        json={"is_active": False}, headers=admin_headers,
    )
    assert res.status_code == 422

    res = client.patch(
        f"/api/admin/users/{admin_user['id']}",
        json={"role": "user"}, headers=admin_headers,
    )
    assert res.status_code == 422


def test_activate_deactivate_user(client, admin_headers, user_headers):
    users = client.get("/api/admin/users", headers=admin_headers).json()
    target = next(u for u in users if u["email"] == "user1@test.ly")

    res = client.patch(
        f"/api/admin/users/{target['id']}",
        json={"is_active": False}, headers=admin_headers,
    )
    assert res.status_code == 200

    # Deactivated user is rejected on token use
    assert client.get("/api/auth/me", headers=user_headers).status_code == 401

    client.patch(f"/api/admin/users/{target['id']}",
                 json={"is_active": True}, headers=admin_headers)
    assert client.get("/api/auth/me", headers=user_headers).status_code == 200


def test_notification_broadcast(client, admin_headers, user_headers):
    res = client.post(
        "/api/admin/notifications",
        json={"title": "تحديث القوانين", "body": "تمت إضافة قانون جديد للقاعدة."},
        headers=admin_headers,
    )
    assert res.status_code == 201

    rows = client.get("/api/notifications", headers=user_headers).json()
    assert any(n["title"] == "تحديث القوانين" and not n["is_read"] for n in rows)

    nid = rows[0]["id"]
    assert client.post(f"/api/notifications/{nid}/read", headers=user_headers).status_code == 200
    rows = client.get("/api/notifications", headers=user_headers).json()
    assert all(n["is_read"] for n in rows if n["id"] == nid)


def test_documents_registry_synced(client, admin_headers):
    docs = client.get("/api/admin/documents", headers=admin_headers).json()
    assert len(docs) >= 12
    assert any(d["doc_id"] == "LAW_12_2010" and d["is_builtin"] for d in docs)
    assert all(d["status"] == "indexed" for d in docs if d["is_builtin"])


def test_delete_builtin_document_protected(client, admin_headers):
    res = client.delete("/api/admin/documents/LAW_12_2010", headers=admin_headers)
    assert res.status_code == 403


def test_health_report(client, admin_headers):
    res = client.get("/api/admin/health", headers=admin_headers)
    assert res.status_code == 200
    comps = res.json()["components"]
    assert comps["database"]["ok"] is True
    assert comps["ai_layer"]["status"] == "ready"
    assert comps["vector_index"]["indexed_chunks"] > 0


def test_backup_download(client, admin_headers):
    res = client.get("/api/admin/backup", headers=admin_headers)
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/octet-stream"
    assert len(res.content) > 0


def test_login_rate_limited(client):
    payload = {"email": "rl@test.ly", "password": "wrong-password"}
    statuses = []
    for _ in range(11):
        statuses.append(client.post("/api/auth/login", json=payload).status_code)
    assert 429 in statuses
