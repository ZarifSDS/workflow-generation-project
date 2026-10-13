import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_healthz_reports_database_ok(client):
    response = client.get("/healthz/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


@pytest.mark.django_db
def test_studio_overview_requires_login(client):
    response = client.get(reverse("studio:overview"))
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


@pytest.mark.django_db
def test_studio_overview_renders_for_admin(admin_client):
    response = admin_client.get(reverse("studio:overview"))
    assert response.status_code == 200
    assert b"Content Studio" in response.content
    assert b"Pipeline" in response.content


@pytest.mark.django_db
def test_content_studio_menu_in_admin_sidebar(admin_client):
    response = admin_client.get(reverse("wagtailadmin_home"))
    assert response.status_code == 200
    assert b"content-studio" in response.content
