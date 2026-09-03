import base64
import copy
import json
import plistlib

import pytest
from fastapi.testclient import TestClient

import app
import auto_app
from shortcut_date_auto import PRODUCT_NAME, build_date_auto_shortcut


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
    assert result["model_version"] == "0.9.0"
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


def test_new_shortcut_keeps_v2_match_selection_and_saves_one_joint_analysis():
    payload = build_date_auto_shortcut(
        base64.b64decode(app._PREPARED_SHORTCUT_B64),
        "https://elite.example.test",
    )
    workflow = plistlib.loads(payload)
    assert workflow["WFWorkflowName"] == PRODUCT_NAME
    actions = workflow["WFWorkflowActions"]
    identifiers = [item["WFWorkflowActionIdentifier"] for item in actions]
    assert identifiers.count("is.workflow.actions.ask") == 1
    assert identifiers.count("is.workflow.actions.choosefromlist") == 1
    assert identifiers.count("is.workflow.actions.repeat.each") == 2
    assert identifiers[-1] == "is.workflow.actions.documentpicker.save"
    serialized = str(workflow)
    assert "/api/forebet-auto/export" in serialized
    assert "/api/selected-analysis" in serialized
    assert "Forebet:" not in serialized
    assert identifiers.count("is.workflow.actions.documentpicker.save") == 1
    assert identifiers.count("is.workflow.actions.conditional") == 0
    assert identifiers.count("is.workflow.actions.file.createfolder") == 1
    assert "_FootyStats_Forebet_Analyse.json" in serialized
    for old_name in (
        "_MatchDaten.json", "_LeagueDaten.json", "_FormDaten.json",
        "_TableDaten.json", "_PlayerDaten.json", "_ForebetDaten.json",
    ):
        assert old_name not in serialized
    for variable in (
        "LeagueDatenFinal", "MatchDaten", "FormDatenFinal",
        "TableDatenFinal", "PlayerDatenFinal", "ForebetDaten",
    ):
        assert variable in serialized
    for variable in ("LeagueSeiten", "FormTeams", "PlayerSeiten"):
        first = next(
            item for item in actions
            if item.get("WFWorkflowActionParameters", {}).get("WFVariableName") == variable
        )
        assert first["WFWorkflowActionIdentifier"] == "is.workflow.actions.appendvariable"


def test_http_health_and_homepage_identify_new_product_and_backup():
    client = TestClient(app.app)
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {
        "ok": True,
        "version": "0.9.0",
        "footystats_backup": "0.4.0",
        "forebet_ensemble": True,
        "v2_match_selection": True,
        "single_joint_archive": True,
        "hubsign_format": "AEA1",
        "shortcut_delivery": "pre_signed",
    }
    homepage = client.get("/")
    assert homepage.status_code == 200
    assert "FootyStats + Forebet ELITE Analyse v0.9.0" in homepage.text
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


def _payload_json():
    files = {app._source_kind(item["name"]): item["data"] for item in bundle()}
    return {
        "matchData": files["match"],
        "leagueData": files["league"],
        "formData": files["form"],
        "tableData": files["table"],
        "playerData": files["player"],
        "forebetData": files["forebet"],
    }


def test_elite_candidate_does_not_return_archive_for_non_playing_match():
    client = TestClient(app.app)
    response = client.post("/api/elite-candidate", json=_payload_json())

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["decision"] == "AUSLASSEN"
    assert body["save"] is False
    assert "archive" not in body


def test_elite_candidate_returns_exactly_one_joint_archive_for_playing_match(monkeypatch):
    pair = app.select_pair(bundle())

    def playing(_parsed):
        return {"ok": True, "decision": "SPIELEN", "_archive_pair": pair}

    monkeypatch.setattr(app, "_analyze_bundle", playing)
    monkeypatch.setattr(app, "_archive_package", lambda parsed, selected, result: {
        "all_six_sources": len(parsed) == 6,
        "decision": result["decision"],
        "pair_ok": selected["ok"],
    })
    client = TestClient(app.app)
    response = client.post("/api/elite-candidate", json=_payload_json())

    assert response.status_code == 200
    assert response.json()["save"] is True
    assert response.json()["archive"] == {
        "all_six_sources": True,
        "decision": "SPIELEN",
        "pair_ok": True,
    }


def test_selected_analysis_returns_joint_archive_for_user_choice_even_when_not_playing():
    client = TestClient(app.app)
    response = client.post("/api/selected-analysis", json=_payload_json())

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["decision"] == "AUSLASSEN"
    assert body["archive"]["source_coverage"]["missing"] == []
    assert set(body["archive"]["sources"]) == {
        "match", "league", "form", "table", "player", "forebet",
    }
    assert body["archive"]["analysis"]["ensemble"]["active"] is True


def test_selected_analysis_archives_forebet_failure_instead_of_selecting_another_game():
    payload = _payload_json()
    payload["forebetData"] = {
        "ok": False,
        "match_id": MATCH_ID,
        "phase": "FOREBET_UNAVAILABLE",
        "error": "nicht sicher gefunden",
    }
    client = TestClient(app.app)
    response = client.post("/api/selected-analysis", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["decision"] == "ANALYSE NICHT MÖGLICH"
    assert body["archive"]["source_coverage"]["missing"] == []
    assert body["archive"]["analysis"]["phase"] == "FOREBET_VALIDATION_FAILED"


def test_forebet_export_error_is_a_file_and_does_not_abort_daily_shortcut(monkeypatch):
    def fail(**_kwargs):
        raise auto_app.ForebetAutoError("nicht gefunden")

    monkeypatch.setattr(auto_app, "build_snapshot", fail)
    client = TestClient(auto_app.app)
    response = client.get(
        "/api/forebet-auto/export",
        params={"match_id": MATCH_ID, "home": "Home FC", "away": "Away FC", "date": "2026-09-02"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["phase"] == "FOREBET_UNAVAILABLE"
    assert body["match_id"] == MATCH_ID


def test_forebet_score_and_average_goals_are_real_decision_gates():
    forebet = app._forebet_snapshot(bundle()[5]["data"], app.mf(bundle()[0]["data"]))
    over = app._forebet_internal_coherence(forebet, "over_2_5")
    under = app._forebet_internal_coherence(forebet, "under_2_5")
    assert over["passed"] is True
    assert under["passed"] is False


def test_pre_signed_shortcut_download_is_apple_aea1():
    client = TestClient(app.app)
    get_response = client.get("/api/shortcut-download")
    old_helper_response = client.post("/api/hubsign-sign", data={"api_key": "ignored"})

    for response in (get_response, old_helper_response):
        assert response.status_code == 200
        assert response.content.startswith(b"AEA1")
        assert len(response.content) > 20_000
        assert response.headers["content-type"] == "application/octet-stream"
        assert "FootyStats + Forebet ELITE V2.shortcut" in response.headers["content-disposition"]


def test_pre_signed_shortcut_refuses_corrupt_embedded_payload(monkeypatch):
    monkeypatch.setattr(app._signed_shortcut, "SIGNED_ELITE_SHORTCUT_B64", base64.b64encode(b"bplist00-not-signed").decode())
    client = TestClient(app.app)
    response = client.get("/api/shortcut-download")

    assert response.status_code == 500
    assert "AEA1" in response.json()["detail"]


def test_hubsign_helper_never_claims_unsigned_download_is_valid():
    client = TestClient(app.app)
    response = client.get("/hubsign-helper")

    assert response.status_code == 200
    assert "HubSign API-Key" not in response.text
    assert "magic!=='AEA1'" in response.text
    assert "/api/shortcut-download" in response.text
