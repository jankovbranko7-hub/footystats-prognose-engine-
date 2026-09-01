import base64
import copy
import json
import plistlib

import pytest
from fastapi.testclient import TestClient

import app


MATCH_ID = 123456
HOME_ID = 10
AWAY_ID = 20


def team(team_id, name, home_xg, home_xga, away_xg, away_xga):
    return {
        "id": team_id,
        "name": name,
        "stats": {
            "seasonMatchesPlayed_overall": 24,
            "seasonMatchesPlayed_home": 12,
            "seasonMatchesPlayed_away": 12,
            "xg_for_avg_home": home_xg,
            "xg_against_avg_home": home_xga,
            "xg_for_avg_away": away_xg,
            "xg_against_avg_away": away_xga,
            "seasonBTTSPercentage_home": 55,
            "seasonBTTSPercentage_away": 50,
            "seasonOver25Percentage_home": 58,
            "seasonOver25Percentage_away": 52,
            "seasonUnder25Percentage_home": 42,
            "seasonUnder25Percentage_away": 48,
            "winPercentage_home": 50,
            "winPercentage_away": 33,
        },
    }


def bundle(forebet_raw="45;28;27;60;62;2-1;2,8;https://www.forebet.com/en/test"):
    teams = [
        team(HOME_ID, "Home FC", 1.70, 1.05, 1.25, 1.40),
        team(AWAY_ID, "Away FC", 1.45, 1.20, 1.48, 1.28),
        team(30, "Team 3", 1.60, 1.20, 1.22, 1.46),
        team(40, "Team 4", 1.52, 1.24, 1.30, 1.38),
        team(50, "Team 5", 1.66, 1.10, 1.18, 1.50),
        team(60, "Team 6", 1.42, 1.30, 1.36, 1.32),
    ]
    match = {
        "data": {
            "id": MATCH_ID,
            "homeID": HOME_ID,
            "awayID": AWAY_ID,
            "home_name": "Home FC",
            "away_name": "Away FC",
            "competition_id": 77,
            "season": "2026/2027",
            "date": "2026-09-02",
        }
    }
    return [
        {"name": f"{MATCH_ID}_MatchDaten.json", "data": match},
        {"name": "77_LeagueDaten.json", "data": {"data": teams}},
        {"name": f"{MATCH_ID}_FormDaten.json", "data": {"data": []}},
        {"name": f"{MATCH_ID}_TableDaten.json", "data": {"data": []}},
        {"name": f"{MATCH_ID}_PlayerDaten.json", "data": {"data": []}},
        {
            "name": f"{MATCH_ID}_ForebetDaten.json",
            "data": {
                "schema": "forebet-manual-v1",
                "match_id": MATCH_ID,
                "raw_entry": forebet_raw,
            },
        },
    ]


def test_six_file_bundle_uses_both_models_and_changes_probabilities():
    parsed = bundle()
    pair = app.select_pair(parsed)
    assert pair["ok"] is True
    assert set(pair["source_files"]) == {"match", "league", "form", "table", "player", "forebet"}

    result = app._analyze_bundle(parsed)
    assert result["ok"] is True
    assert result["model_version"] == "0.6.0"
    assert result["ensemble"]["active"] is True
    assert result["ensemble"]["weights"] == {"footystats": 0.5, "forebet": 0.5}
    assert result["forebet_model"]["odds_used"] is False

    footystats = result["footystats_model"]["probabilities"]["btts_yes"]
    forebet = result["forebet_model"]["probabilities"]["btts_yes"]
    combined = result["probabilities"]["btts_yes"]
    assert min(footystats, forebet) <= combined <= max(footystats, forebet)
    assert combined != pytest.approx(footystats)


def test_missing_forebet_is_rejected_instead_of_silently_using_five_files():
    result = app._analyze_bundle(bundle()[:-1])
    assert result["ok"] is False
    assert result["phase"] == "FOREBET_DATA_MISSING"


def test_wrong_forebet_match_id_is_rejected():
    parsed = bundle()
    parsed[-1]["data"]["match_id"] = MATCH_ID + 1
    result = app._analyze_bundle(parsed)
    assert result["ok"] is False
    assert result["phase"] == "FOREBET_VALIDATION_FAILED"


@pytest.mark.parametrize(
    "raw",
    [
        "45;28;27;60;62",
        "70;40;20;60;62;2-1;2,8",
        "45;28;27;60;62;kein-tipp;2,8",
        "45;28;27;60;62;2-1;99",
        "45;28;27;60;62;2-1;2,8;https://example.com/test",
    ],
)
def test_invalid_forebet_values_are_rejected(raw):
    result = app._analyze_bundle(bundle(raw))
    assert result["ok"] is False
    assert result["phase"] == "FOREBET_VALIDATION_FAILED"


def test_joint_archive_contains_all_six_sources_and_no_odds_or_secrets():
    parsed = bundle()
    result = app._analyze_bundle(parsed)
    pair = result.pop("_archive_pair")
    package = app._archive_package(parsed, pair, result)
    assert package["archive_schema"] == "footystats-forebet-ios-archive-v2"
    assert package["source_coverage"]["missing"] == []
    assert set(package["sources"]) == {"match", "league", "form", "table", "player", "forebet"}
    serialized = json.dumps(package).lower()
    assert "api_key" not in serialized
    assert '"odds"' not in serialized
    assert package["server_side_persistence"] is False


def test_new_shortcut_is_separate_and_contains_forebet_export_actions():
    workflow = plistlib.loads(base64.b64decode(app._PREPARED_SHORTCUT_V4_B64))
    assert workflow["WFWorkflowName"] == "FootyStats + Forebet Export V4"
    actions = workflow["WFWorkflowActions"]
    assert len(actions) == 94
    assert [item["WFWorkflowActionIdentifier"] for item in actions[-5:]] == [
        "is.workflow.actions.ask",
        "is.workflow.actions.gettext",
        "is.workflow.actions.setitemname",
        "is.workflow.actions.gettext",
        "is.workflow.actions.documentpicker.save",
    ]
    prompt = actions[-5]["WFWorkflowActionParameters"]["WFAskActionPrompt"]
    assert "1;X;2;BTTS-Ja;Over-2,5" in prompt
    assert "_PREPARED_SHORTCUT_B64" in app.__dict__


def test_http_health_and_homepage_identify_new_product_and_backup():
    client = TestClient(app.app)
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {
        "ok": True,
        "version": "0.6.0",
        "footystats_backup": "0.4.0",
        "forebet_ensemble": True,
    }
    homepage = client.get("/")
    assert homepage.status_code == 200
    assert "FootyStats + Forebet Super Analyse v0.6.0" in homepage.text
    assert "alle sechs JSON-Dateien" in homepage.text


def test_legacy_two_file_endpoint_cannot_bypass_forebet():
    client = TestClient(app.app)
    response = client.post(
        "/api/predict-files",
        files={
            "match_file": ("123456_MatchDaten.json", b"{}", "application/json"),
            "league_file": ("77_LeagueDaten.json", b"{}", "application/json"),
        },
    )
    assert response.status_code == 422
    assert "keinen unvollständigen Zwei-Dateien-Weg" in response.json()["detail"]


def test_bundle_and_archive_http_endpoints_complete_the_full_flow():
    client = TestClient(app.app)
    files = [
        ("files", (item["name"], json.dumps(item["data"]).encode(), "application/json"))
        for item in bundle()
    ]
    prediction = client.post("/api/predict-bundle", files=files)
    assert prediction.status_code == 200
    body = prediction.json()
    assert body["ok"] is True
    assert body["ensemble"]["active"] is True
    assert "_archive_pair" not in body

    files = [
        ("files", (item["name"], json.dumps(item["data"]).encode(), "application/json"))
        for item in bundle()
    ]
    archive = client.post("/api/archive-bundle", files=files)
    assert archive.status_code == 200
    assert archive.headers["content-type"].startswith("application/json")
    assert "FootyStats-Forebet-Archiv" in archive.headers["content-disposition"]
    package = archive.json()
    assert package["source_coverage"]["missing"] == []
    assert package["analysis"]["ensemble"]["active"] is True
