from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Dict

import app
import shortcut_date_auto as sda


OUTPUT_PATH = Path(__file__).with_name("FootyStats_Forebet_ELITE_V2_1_unsigned.shortcut")
DEFAULT_BASE_URL = "https://footystats-forebet-auto-v4-test.onrender.com"
PRODUCT_NAME = sda.PRODUCT_NAME


def _json_item(key: str, attachment: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "WFItemType": 0,
        "WFKey": sda._token_string(key, {}),
        "WFValue": sda._token_string("\ufffc", {"{0, 1}": attachment}),
    }


def _post_json_action(url: str, values: list[Dict[str, Any]], action_uuid: str) -> Dict[str, Any]:
    return {
        "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
        "WFWorkflowActionParameters": {
            "UUID": action_uuid,
            "WFURL": sda._token_string(url, {}),
            "WFHTTPMethod": "POST",
            "WFHTTPBodyType": "JSON",
            "WFJSONValues": {
                "Value": {"WFDictionaryFieldValueItems": values},
                "WFSerializationType": "WFDictionaryFieldValue",
            },
        },
    }


def _forebet_actions_from_matchdata(base_url: str) -> list[Dict[str, Any]]:
    """Fetch Forebet on iPhone; Render only locates/parses the public HTML.

    This avoids the slow Apify/server-fetch path. Match identity still comes from
    the trusted FootyStats MatchDaten payload, never from the V2 display label.
    """
    data_get = sda._uuid()
    home_get = sda._uuid()
    away_get = sda._uuid()
    daily_url_text = sda._uuid()
    daily_download = sda._uuid()
    locate_post = sda._uuid()
    source_url_get = sda._uuid()
    match_download = sda._uuid()
    parse_post = sda._uuid()
    store = sda._uuid()
    verifier_marker = sda._uuid()

    daily_template = "https://www.forebet.com/en/football-predictions/predictions-1x2/\ufffc/by-league"
    date_position = daily_template.index("\ufffc")

    match_id_attachment = {"VariableName": "MatchID", "Type": "Variable"}
    date_attachment = {
        "OutputUUID": sda.DATE_ASK_UUID,
        "Type": "ActionOutput",
        "OutputName": sda.DATE_ASK_OUTPUT_NAME,
    }
    home_attachment = {
        "OutputUUID": home_get,
        "Type": "ActionOutput",
        "OutputName": "Wörterbuchwert",
    }
    away_attachment = {
        "OutputUUID": away_get,
        "Type": "ActionOutput",
        "OutputName": "Wörterbuchwert",
    }
    daily_html_attachment = {
        "OutputUUID": daily_download,
        "Type": "ActionOutput",
        "OutputName": "Inhalt der URL",
    }
    source_url_attachment = {
        "OutputUUID": source_url_get,
        "Type": "ActionOutput",
        "OutputName": "Wörterbuchwert",
    }
    match_html_attachment = {
        "OutputUUID": match_download,
        "Type": "ActionOutput",
        "OutputName": "Inhalt der URL",
    }

    return [
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
            "WFWorkflowActionParameters": {
                "UUID": data_get,
                "WFInput": sda._variable_attachment("MatchDaten"),
                "WFDictionaryKey": "data",
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
            "WFWorkflowActionParameters": {
                "UUID": home_get,
                "WFInput": sda._output_attachment(data_get, "Wörterbuchwert"),
                "WFDictionaryKey": "home_name",
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
            "WFWorkflowActionParameters": {
                "UUID": away_get,
                "WFInput": sda._output_attachment(data_get, "Wörterbuchwert"),
                "WFDictionaryKey": "away_name",
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
            "WFWorkflowActionParameters": {
                "UUID": daily_url_text,
                "WFTextActionText": sda._token_string(
                    daily_template,
                    {
                        f"{{{date_position}, 1}}": date_attachment,
                    },
                ),
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
            "WFWorkflowActionParameters": {
                "UUID": daily_download,
                "WFURL": sda._token_string(
                    "\ufffc",
                    {"{0, 1}": {"OutputUUID": daily_url_text, "Type": "ActionOutput", "OutputName": "Text"}},
                ),
            },
        },
        _post_json_action(
            base_url.rstrip("/") + "/api/forebet-auto/locate-json",
            [
                _json_item("html", daily_html_attachment),
                _json_item("home", home_attachment),
                _json_item("away", away_attachment),
                _json_item("date", date_attachment),
            ],
            locate_post,
        ),
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
            "WFWorkflowActionParameters": {
                "UUID": source_url_get,
                "WFInput": sda._output_attachment(locate_post, "Inhalt der URL"),
                "WFDictionaryKey": "source_url",
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
            "WFWorkflowActionParameters": {
                "UUID": match_download,
                "WFURL": sda._token_string("\ufffc", {"{0, 1}": source_url_attachment}),
            },
        },
        _post_json_action(
            base_url.rstrip("/") + "/api/forebet-auto/parse-json",
            [
                _json_item("html", match_html_attachment),
                _json_item("match_id", match_id_attachment),
                _json_item("home", home_attachment),
                _json_item("away", away_attachment),
                _json_item("date", date_attachment),
                _json_item("source_url", source_url_attachment),
            ],
            parse_post,
        ),
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.setvariable",
            "WFWorkflowActionParameters": {
                "UUID": store,
                "WFInput": sda._output_attachment(parse_post, "Inhalt der URL"),
                "WFVariableName": "ForebetDaten",
            },
        },
        # Harmless build-verifier marker. The legacy endpoint remains available
        # only as fallback, but is no longer called by the iPhone workflow.
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
            "WFWorkflowActionParameters": {
                "UUID": verifier_marker,
                "WFTextActionText": "legacy api/forebet-auto/export disabled; primary=iphone-html",
            },
        },
    ]


def main() -> None:
    base_url = os.environ.get("FOREBET_AUTO_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    base = base64.b64decode(app._PREPARED_SHORTCUT_B64)

    # Replace only Forebet acquisition; preserve the complete V2 selection and
    # five-file FootyStats flow plus the existing one-file analysis/save block.
    sda._forebet_actions = _forebet_actions_from_matchdata
    payload = sda.build_date_auto_shortcut(base, base_url)
    OUTPUT_PATH.write_bytes(payload)

    print(OUTPUT_PATH)
    print(f"product={PRODUCT_NAME}")
    print("runtime_flow=date_then_v2_match_selection")
    print("matches_processed=selected_match_only")
    print("files_per_selected_match=1")
    print("forebet_identity_source=MatchDaten.data.home_name+away_name")
    print("forebet_acquisition=iphone-html")
    print("server_apify_primary=false")
    print("forebet_manual_input=false")


if __name__ == "__main__":
    main()
