"""Keyword data providers and keyword filtration (apps/studio/keyword_data.py, Settings › Keyword data
providers). No network: every platform answers through an httpx mock transport."""

import json
from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet
from django.urls import reverse

from apps.ai import redact, secrets
from apps.ai.models import KeywordRules, KeywordSource
from apps.studio import keyword_data, serp

pytestmark = pytest.mark.django_db

SEMRUSH_KEY = "semrush-test-key-0123456789"


@pytest.fixture(autouse=True)
def secrets_key(monkeypatch):
    monkeypatch.setenv(secrets.ENV_NAME, Fernet.generate_key().decode())
    redact.clear_stored_cache()
    yield
    redact.clear_stored_cache()


def _store(name, key, login=""):
    source = KeywordSource.objects.get(name=name)
    source.api_key_encrypted, source.api_key_hint = secrets.encrypt(key), secrets.hint(key)
    if login:
        source.login_encrypted, source.login_hint = secrets.encrypt(login), secrets.hint(login)
    source.save()
    return source


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _brief(**extra):
    fields = {"skeywords": [], "region": "UK", **extra}
    return SimpleNamespace(pkeyword="risk assessment template", topic="Risk assessment template", **fields)


def test_the_three_platforms_are_seeded_without_keys():
    assert list(KeywordSource.objects.values_list("name", flat=True)) == [
        "semrush",
        "dataforseo",
        "keywords_everywhere",
    ]
    assert keyword_data.sources() == []  # nothing is asked until a key is entered


def test_semrush_is_read_from_its_csv_in_the_briefs_database():
    _store("semrush", SEMRUSH_KEY)
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        body = (
            "Keyword;Search Volume;CPC;Competition;Keyword Difficulty Index;Intent\n"
            "risk assessment template;4400;1.20;0.45;52;1\n"
            "hse login;900;0;0.1;30;2\n"
        )
        return httpx.Response(200, text=body)

    label, found, problems = keyword_data.measure(
        ["risk assessment template", "hse login"], "UK", _client(handler)
    )
    assert label == "Semrush" and not problems
    assert (
        seen["type"] == "phrase_these"
        and seen["database"] == "uk"
        and seen["export_columns"] == "Ph,Nq,Cp,Co,Kd,In"
    )
    assert seen["phrase"] == "risk assessment template;hse login"
    metric = found["risk assessment template"]
    assert (metric.volume, metric.difficulty, metric.intent, metric.cpc) == (4400, 52, "informational", 1.2)
    assert found["hse login"].intent == "navigational"


def test_dataforseo_uses_the_login_and_the_region_name():
    _store("dataforseo", "dfs-password-123456", login="me@example.com")
    seen = {}

    def handler(request):
        seen["auth"], seen["body"] = request.headers["Authorization"], json.loads(request.content)
        item = {
            "keyword": "risk assessment template",
            "keyword_info": {"search_volume": 2900, "cpc": 0.9, "competition": 0.3},
            "keyword_properties": {"keyword_difficulty": 41},
            "search_intent_info": {"main_intent": "commercial"},
        }
        return httpx.Response(200, json={"tasks": [{"status_code": 20000, "result": [{"items": [item]}]}]})

    label, found, _ = keyword_data.measure(["risk assessment template"], "AU", _client(handler))
    assert label == "DataForSEO" and seen["auth"].startswith("Basic ")
    assert seen["body"][0]["location_name"] == "Australia" and seen["body"][0]["language_name"] == "English"
    assert (found["risk assessment template"].volume, found["risk assessment template"].difficulty) == (
        2900,
        41,
    )


def test_a_failing_source_is_skipped_for_the_next_and_the_key_never_shows(monkeypatch):
    _store("semrush", SEMRUSH_KEY)
    _store("keywords_everywhere", "ke-test-key-0123456789")

    def handler(request):
        if "semrush" in request.url.host:
            return httpx.Response(200, text=f"ERROR 132 :: API UNITS BALANCE IS ZERO for {SEMRUSH_KEY}")
        item = {"keyword": "risk assessment template", "vol": 1000, "competition": 0.2}
        item["cpc"] = {"currency": "$", "value": "1.05"}
        return httpx.Response(200, json={"data": [item]})

    label, found, problems = keyword_data.measure(["risk assessment template"], "UK", _client(handler))
    assert label == "Keywords Everywhere" and found["risk assessment template"].cpc == 1.05
    assert problems and "API UNITS" in problems[0] and SEMRUSH_KEY not in problems[0]


def test_rules_keep_the_useful_keywords_and_say_why_the_rest_went():
    rules = KeywordRules(
        min_volume=50, max_difficulty=60, drop_navigational=True, exclude_terms="iauditor", max_keywords=25
    )
    brief = _brief(skeywords=["risk register"])
    data = serp.SerpData("serper", "k", "gb", "en", questions=["what is a risk assessment template"],
                         related=["risk assessment templates", "football scores"])  # fmt: skip
    candidates = keyword_data.collect(
        brief,
        data,
        ["risk assessment template iauditor", "risk assessment template hse", "risk assessment form"],
    )
    metrics = {
        "risk assessment template hse": keyword_data.Metric("risk assessment template hse", 20),
        "risk assessment form": keyword_data.Metric("risk assessment form", 900, difficulty=75),
        "what is a risk assessment template": keyword_data.Metric("what is a risk assessment template", 10),
    }
    keyword_data.apply_rules(candidates, metrics, rules, brief.topic)
    why = {c.keyword: (c.kept, c.reason) for c in candidates}
    assert why["risk assessment template"] == (True, "in the brief")
    assert why["risk register"] == (True, "in the brief")  # the brief's own keywords stay, even off the topic
    assert why["risk assessment template iauditor"] == (False, "contains an excluded term")
    assert why["football scores"][0] is False and "off topic" in why["football scores"][1]
    assert why["risk assessment templates"] == (False, "same words as a kept keyword")
    assert why["risk assessment template hse"] == (False, "under 50 searches a month")
    assert why["risk assessment form"] == (False, "difficulty 75 over 60")
    assert why["what is a risk assessment template"][0] is True  # a question survives a low volume


def test_without_a_source_the_step_still_filters_and_says_volumes_are_unknown():
    data = keyword_data.gather(_brief(), None, ["risk assessment template uk", "cooking recipes"])
    assert data.source == "" and "volumes and difficulty are unknown" in data.note
    text = keyword_data.report(data, "UK")
    assert "## Keyword data" in text and "| risk assessment template uk | autocomplete | – |" in text
    assert "no: off topic" in text


def test_redaction_covers_keyword_keys():
    _store("semrush", SEMRUSH_KEY)
    redact.clear_stored_cache()
    assert redact.redact(f"failed with key={SEMRUSH_KEY}") == "failed with key=[redacted]"


# ---- Settings › Keyword data providers ----


def test_platforms_are_added_edited_and_removed(admin_client):
    page = admin_client.get(reverse("studio:keyword_sources"))
    assert page.status_code == 200 and "Semrush" in page.text and "Rules for keeping a keyword" in page.text
    # Add a platform the studio doesn't read yet: its key is stored, and it says so.
    response = admin_client.post(
        reverse("studio:keyword_source_add"),
        {
            "label": "Ahrefs",
            "name": "ahrefs",
            "platform": "other",
            "order": "40",
            "enabled": "on",
            "api_key": "ahrefs-test-key-123456",
        },  # fmt: skip
    )
    assert response.status_code == 302
    ahrefs = KeywordSource.objects.get(name="ahrefs")
    assert ahrefs.api_key_hint.endswith("3456") and not ahrefs.ready
    assert secrets.decrypt(ahrefs.api_key_encrypted) == "ahrefs-test-key-123456"
    # DataForSEO needs its login with the password.
    form = admin_client.post(
        reverse("studio:keyword_source_edit", args=["dataforseo"]),
        {
            "label": "DataForSEO",
            "platform": "dataforseo",
            "order": "20",
            "enabled": "on",
            "api_key": "dfs-pass-123456",
        },
    )
    assert "DataForSEO needs the API login" in form.content.decode()
    admin_client.post(
        reverse("studio:keyword_source_edit", args=["dataforseo"]),
        {
            "label": "DataForSEO",
            "platform": "dataforseo",
            "order": "5",
            "enabled": "on",
            "api_key": "dfs-pass-123456",
            "login": "me@example.com",
        },  # fmt: skip
    )
    assert keyword_data.sources()[0].name == "dataforseo"  # the lowest order is asked first
    admin_client.post(reverse("studio:keyword_source_key_remove", args=["dataforseo"]))
    assert not KeywordSource.objects.get(name="dataforseo").api_key_encrypted
    admin_client.post(reverse("studio:keyword_source_delete", args=["semrush"]))
    assert not KeywordSource.objects.filter(name="semrush").exists()


def test_rules_are_saved_and_the_page_is_for_superusers_only(admin_client, client, django_user_model):
    admin_client.post(
        reverse("studio:keyword_sources"),
        {
            "action": "rules",
            "min_volume": "100",
            "max_difficulty": "50",
            "exclude_terms": "safetyculture",
            "max_keywords": "15",
        },  # fmt: skip
    )
    rules = KeywordRules.current()
    assert (rules.min_volume, rules.max_difficulty, rules.drop_navigational, rules.excluded()) == (
        100,
        50,
        False,
        ["safetyculture"],
    )
    editor = django_user_model.objects.create_user("editor", password="x", is_staff=True)
    client.force_login(editor)
    assert client.get(reverse("studio:keyword_sources")).status_code in (302, 403)


@pytest.mark.search_step
def test_the_search_step_carries_the_keyword_table(monkeypatch, admin_user):
    from apps.studio import executors, services
    from apps.studio.models import ContentBrief

    brief = ContentBrief.objects.create(topic="Risk assessment template", pkeyword="risk assessment template",
                                        region="UK", created_by=admin_user)  # fmt: skip
    run = services.create_run(brief, {})
    step = run.steps.get(key="search_results")
    data = serp.SerpData("serper", "k", "gb", "en", results=[serp.Result(1, "A", "https://a.uk")])
    monkeypatch.setattr(serp, "search", lambda *a, **k: data)
    monkeypatch.setattr(serp, "autocomplete", lambda *a, **k: ["risk assessment template uk"])
    monkeypatch.setattr(serp, "read_pages", lambda *a, **k: [])
    output = executors.search_results(step)
    assert "## Keyword data" in output.content and "risk assessment template uk" in output.content
    assert output.extra_metrics["keywords"]["kept"][0] == "risk assessment template"
