from __future__ import annotations

import base64
import os
import plistlib
import re
import uuid
from pathlib import Path


APP_PATH = Path(__file__).with_name("app.py")
OUTPUT_PATH = Path(__file__).with_name("FootyStats_Forebet_AUTO_V4_TEST_unsigned.shortcut")
DEFAULT_BASE_URL = "https://footystats-forebet-auto-v4-test.onrender.com"
BASE_URL = os.environ.get("FOREBET_AUTO_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
DATE_ASK_UUID = "BD34DEEF-AD61-42EE-A348-AA244E6DEEFE"
DATE_ASK_OUTPUT_NAME = "Nach Eingabe fragen"


def new_uuid():
    return str(uuid.uuid4()).upper()


def token_string(text, attachments):
    return {
        "Value": {"string": text, "attachmentsByRange": attachments},
        "WFSerializationType": "WFTextTokenString",
    }


def output_attachment(output_uuid, output_name):
    return {
        "Value": {
            "OutputUUID": output_uuid,
            "Type": "ActionOutput",
            "OutputName": output_name,
        },
        "WFSerializationType": "WFTextTokenAttachment",
    }


def variable_attachment(name):
    return {
        "Value": {"VariableName": name, "Type": "Variable"},
        "WFSerializationType": "WFTextTokenAttachment",
    }


def main():
    if not BASE_URL.startswith("https://"):
        raise SystemExit("FOREBET_AUTO_BASE_URL muss eine HTTPS-URL sein.")

    app_text = APP_PATH.read_text(encoding="utf-8")
    encoded_match = re.search(r'_PREPARED_SHORTCUT_B64 = "([A-Za-z0-9+/=]+)"', app_text)
    if not encoded_match:
        raise SystemExit("Originaler V2-Kurzbefehl wurde in app.py nicht gefunden.")
    workflow = plistlib.loads(base64.b64decode(encoded_match.group(1)))
    actions = workflow["WFWorkflowActions"]

    # Der bestehende V2 bleibt die Basis. Nur im neuen AUTO-V4-Testworkflow
    # werden vorhandene Dateien desselben Match-Laufs sauber überschrieben.
    for action in actions:
        if action.get("WFWorkflowActionIdentifier") == "is.workflow.actions.documentpicker.save":
            action.setdefault("WFWorkflowActionParameters", {})["WFSaveFileOverwrite"] = True

    # Sicherheitsprüfung: Das Datum muss aus dem bereits vorhandenen
    # "Welcher Tag?"-Schritt des V2 stammen. So wird kein neues Eingabefeld erzeugt.
    if not any(
        action.get("WFWorkflowActionIdentifier") == "is.workflow.actions.ask"
        and action.get("WFWorkflowActionParameters", {}).get("UUID") == DATE_ASK_UUID
        for action in actions
    ):
        raise SystemExit("Der erwartete V2-Datumsschritt wurde nicht gefunden.")

    home_get = new_uuid()
    home_enc = new_uuid()
    away_get = new_uuid()
    away_enc = new_uuid()
    url_text = new_uuid()
    download = new_uuid()
    rename = new_uuid()
    path_text = new_uuid()
    save = new_uuid()

    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
        "WFWorkflowActionParameters": {
            "UUID": home_get,
            "WFInput": variable_attachment("        GefundenesSpiel"),
            "WFDictionaryKey": "home_name",
        },
    })
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.urlencode",
        "WFWorkflowActionParameters": {
            "UUID": home_enc,
            "WFInput": output_attachment(home_get, "Wörterbuchwert"),
            "WFEncodeMode": "Encode",
        },
    })
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
        "WFWorkflowActionParameters": {
            "UUID": away_get,
            "WFInput": variable_attachment("        GefundenesSpiel"),
            "WFDictionaryKey": "away_name",
        },
    })
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.urlencode",
        "WFWorkflowActionParameters": {
            "UUID": away_enc,
            "WFInput": output_attachment(away_get, "Wörterbuchwert"),
            "WFEncodeMode": "Encode",
        },
    })

    # Das Datum kommt automatisch aus dem vorhandenen V2-Schritt. Der Nutzer
    # muss für Forebet nichts zusätzlich eingeben.
    template = BASE_URL + "/api/forebet-auto?match_id=\ufffc&home=\ufffc&away=\ufffc&date=\ufffc"
    p1 = template.index("\ufffc")
    p2 = template.index("\ufffc", p1 + 1)
    p3 = template.index("\ufffc", p2 + 1)
    p4 = template.index("\ufffc", p3 + 1)
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
        "WFWorkflowActionParameters": {
            "UUID": url_text,
            "WFTextActionText": token_string(template, {
                f"{{{p1}, 1}}": {"VariableName": "MatchID", "Type": "Variable"},
                f"{{{p2}, 1}}": {"OutputUUID": home_enc, "Type": "ActionOutput", "OutputName": "URL Encoded Text"},
                f"{{{p3}, 1}}": {"OutputUUID": away_enc, "Type": "ActionOutput", "OutputName": "URL Encoded Text"},
                f"{{{p4}, 1}}": {"OutputUUID": DATE_ASK_UUID, "Type": "ActionOutput", "OutputName": DATE_ASK_OUTPUT_NAME},
            }),
        },
    })
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
        "WFWorkflowActionParameters": {
            "UUID": download,
            "WFURL": token_string("\ufffc", {
                "{0, 1}": {"OutputUUID": url_text, "Type": "ActionOutput", "OutputName": "Text"}
            }),
        },
    })
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.setitemname",
        "WFWorkflowActionParameters": {
            "UUID": rename,
            "WFName": token_string("\ufffc_ForebetDaten.json", {
                "{0, 1}": {"VariableName": "MatchID", "Type": "Variable"},
            }),
            "WFInput": output_attachment(download, "Inhalt der URL"),
            "WFDontIncludeFileExtension": False,
        },
    })
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
        "WFWorkflowActionParameters": {
            "UUID": path_text,
            "WFTextActionText": token_string("\ufffc/\ufffc_ForebetDaten.json", {
                "{0, 1}": {"VariableName": "MatchID", "Type": "Variable"},
                "{2, 1}": {"VariableName": "MatchID", "Type": "Variable"},
            }),
        },
    })
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.documentpicker.save",
        "WFWorkflowActionParameters": {
            "UUID": save,
            "WFInput": output_attachment(rename, "Umbenanntes Objekt"),
            "WFAskWhereToSave": False,
            "WFSaveFileOverwrite": True,
            "WFFileDestinationPath": token_string("\ufffc", {
                "{0, 1}": {"OutputUUID": path_text, "Type": "ActionOutput", "OutputName": "Text"},
            }),
        },
    })

    workflow["WFWorkflowName"] = "FootyStats + Forebet AUTO V4 TEST"
    payload = plistlib.dumps(workflow, fmt=plistlib.FMT_BINARY, sort_keys=False)
    check = plistlib.loads(payload)

    if len(check.get("WFWorkflowActions", [])) != 98:
        raise SystemExit("Unerwartete Aktionszahl; Builder stoppt sicherheitshalber.")
    if not payload.startswith(b"bplist00"):
        raise SystemExit("Erzeugte Datei ist kein Apple Binary Property List Shortcut.")
    if any(
        action.get("WFWorkflowActionIdentifier") == "is.workflow.actions.ask"
        and "Forebet:" in str(action.get("WFWorkflowActionParameters", {}).get("WFAskActionPrompt", ""))
        for action in check["WFWorkflowActions"]
    ):
        raise SystemExit("Manuelle Forebet-Eingabe wurde unerwartet gefunden.")

    OUTPUT_PATH.write_bytes(payload)
    print(OUTPUT_PATH)
    print(f"actions={len(check['WFWorkflowActions'])}")
    print(f"endpoint={BASE_URL}/api/forebet-auto")
    print("forebet_manual_input=false")
    print("date_source=existing_v2_ask")


if __name__ == "__main__":
    main()
