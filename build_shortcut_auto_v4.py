from __future__ import annotations

import base64
import copy
import os
import plistlib
import re
import uuid
from pathlib import Path


APP_PATH = Path(__file__).with_name("app.py")
OUTPUT_PATH = Path(__file__).with_name("FootyStats_Forebet_AUTO_V4_unsigned.shortcut")
BASE_URL = os.environ.get("FOREBET_AUTO_BASE_URL", "").rstrip("/")


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
        raise SystemExit("FOREBET_AUTO_BASE_URL muss zuerst auf die HTTPS-URL des separaten Testservices gesetzt werden.")

    app_text = APP_PATH.read_text(encoding="utf-8")
    encoded = re.search(r'_PREPARED_SHORTCUT_B64 = "([A-Za-z0-9+/=]+)"', app_text).group(1)
    workflow = plistlib.loads(base64.b64decode(encoded))
    actions = workflow["WFWorkflowActions"]

    for action in actions:
        if action.get("WFWorkflowActionIdentifier") == "is.workflow.actions.documentpicker.save":
            action.setdefault("WFWorkflowActionParameters", {})["WFSaveFileOverwrite"] = True

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

    template = BASE_URL + "/api/forebet-auto?match_id=\ufffc&home=\ufffc&away=\ufffc"
    p1 = template.index("\ufffc")
    p2 = template.index("\ufffc", p1 + 1)
    p3 = template.index("\ufffc", p2 + 1)
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
        "WFWorkflowActionParameters": {
            "UUID": url_text,
            "WFTextActionText": token_string(template, {
                f"{{{p1}, 1}}": {"VariableName": "MatchID", "Type": "Variable"},
                f"{{{p2}, 1}}": {"OutputUUID": home_enc, "Type": "ActionOutput", "OutputName": "URL Encoded Text"},
                f"{{{p3}, 1}}": {"OutputUUID": away_enc, "Type": "ActionOutput", "OutputName": "URL Encoded Text"},
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

    workflow["WFWorkflowName"] = "FootyStats + Forebet AUTO V4"
    payload = plistlib.dumps(workflow, fmt=plistlib.FMT_BINARY, sort_keys=False)
    check = plistlib.loads(payload)
    if len(check.get("WFWorkflowActions", [])) != 98:
        raise SystemExit("Unerwartete Aktionszahl; Builder stoppt sicherheitshalber.")
    OUTPUT_PATH.write_bytes(payload)
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
