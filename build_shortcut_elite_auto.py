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


def _forebet_actions_from_matchdata(base_url: str) -> list[Dict[str, Any]]:
    """Build Forebet request from the trusted FootyStats MatchDaten payload.

    The V2 selection dictionary can contain only an id/label and therefore must
    not be used as the source of home_name/away_name. MatchDaten is already
    loaded at this point and contains data.home_name/data.away_name.
    """
    data_get = sda._uuid()
    home_get = sda._uuid()
    home_enc = sda._uuid()
    away_get = sda._uuid()
    away_enc = sda._uuid()
    url_text = sda._uuid()
    download = sda._uuid()
    store = sda._uuid()

    template = base_url.rstrip("/") + "/api/forebet-auto/export?match_id=\ufffc&home=\ufffc&away=\ufffc&date=\ufffc"
    positions = []
    start = 0
    for _ in range(4):
        position = template.index("\ufffc", start)
        positions.append(position)
        start = position + 1

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
            "WFWorkflowActionIdentifier": "is.workflow.actions.urlencode",
            "WFWorkflowActionParameters": {
                "UUID": home_enc,
                "WFInput": sda._output_attachment(home_get, "Wörterbuchwert"),
                "WFEncodeMode": "Encode",
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
            "WFWorkflowActionIdentifier": "is.workflow.actions.urlencode",
            "WFWorkflowActionParameters": {
                "UUID": away_enc,
                "WFInput": sda._output_attachment(away_get, "Wörterbuchwert"),
                "WFEncodeMode": "Encode",
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
            "WFWorkflowActionParameters": {
                "UUID": url_text,
                "WFTextActionText": sda._token_string(
                    template,
                    {
                        f"{{{positions[0]}, 1}}": {"VariableName": "MatchID", "Type": "Variable"},
                        f"{{{positions[1]}, 1}}": {"OutputUUID": home_enc, "Type": "ActionOutput", "OutputName": "URL Encoded Text"},
                        f"{{{positions[2]}, 1}}": {"OutputUUID": away_enc, "Type": "ActionOutput", "OutputName": "URL Encoded Text"},
                        f"{{{positions[3]}, 1}}": {"OutputUUID": sda.DATE_ASK_UUID, "Type": "ActionOutput", "OutputName": sda.DATE_ASK_OUTPUT_NAME},
                    },
                ),
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
            "WFWorkflowActionParameters": {
                "UUID": download,
                "WFURL": sda._token_string(
                    "\ufffc",
                    {"{0, 1}": {"OutputUUID": url_text, "Type": "ActionOutput", "OutputName": "Text"}},
                ),
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.setvariable",
            "WFWorkflowActionParameters": {
                "UUID": store,
                "WFInput": sda._output_attachment(download, "Inhalt der URL"),
                "WFVariableName": "ForebetDaten",
            },
        },
    ]


def main() -> None:
    base_url = os.environ.get("FOREBET_AUTO_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    base = base64.b64decode(app._PREPARED_SHORTCUT_B64)

    # Replace only the Forebet identity source; keep the entire V2 selection and
    # five-file FootyStats flow unchanged.
    sda._forebet_actions = _forebet_actions_from_matchdata
    payload = sda.build_date_auto_shortcut(base, base_url)
    OUTPUT_PATH.write_bytes(payload)

    print(OUTPUT_PATH)
    print(f"product={PRODUCT_NAME}")
    print("runtime_flow=date_then_v2_match_selection")
    print("matches_processed=selected_match_only")
    print("files_per_selected_match=1")
    print("forebet_identity_source=MatchDaten.data.home_name+away_name")
    print("forebet_manual_input=false")


if __name__ == "__main__":
    main()
