import base64
import plistlib
import re
import uuid
from pathlib import Path


APP_PATH = Path(__file__).with_name("app.py")
OUTPUT_PATH = Path(__file__).with_name("FootyStats_Forebet_AUTO_V4_unsigned.shortcut")
AUTO_ENDPOINT = "https://footystats-prognose-engine.onrender.com/api/forebet-auto"


def uid():
    return str(uuid.uuid4()).upper()


def token(text, attachments):
    return {
        "Value": {"string": text, "attachmentsByRange": attachments},
        "WFSerializationType": "WFTextTokenString",
    }


def var(name):
    return {
        "Value": {"VariableName": name, "Type": "Variable"},
        "WFSerializationType": "WFTextTokenAttachment",
    }


def out(action_uuid, output_name):
    return {
        "Value": {"OutputUUID": action_uuid, "Type": "ActionOutput", "OutputName": output_name},
        "WFSerializationType": "WFTextTokenAttachment",
    }


def main():
    app_text = APP_PATH.read_text(encoding="utf-8")
    encoded = re.search(r'_PREPARED_SHORTCUT_B64 = "([A-Za-z0-9+/=]+)"', app_text).group(1)
    workflow = plistlib.loads(base64.b64decode(encoded))
    actions = workflow["WFWorkflowActions"]

    # Derselbe Match-Lauf soll keine -2/-3-Duplikate produzieren.
    for action in actions:
        if action.get("WFWorkflowActionIdentifier") == "is.workflow.actions.documentpicker.save":
            action.setdefault("WFWorkflowActionParameters", {})["WFSaveFileOverwrite"] = True

    home_get, home_enc = uid(), uid()
    away_get, away_enc = uid(), uid()
    url_text, download = uid(), uid()
    rename, path_text, save = uid(), uid(), uid()

    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
        "WFWorkflowActionParameters": {
            "UUID": home_get,
            "WFInput": var("        GefundenesSpiel"),
            "WFDictionaryKey": "home_name",
        },
    })
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.urlencode",
        "WFWorkflowActionParameters": {
            "UUID": home_enc,
            "WFInput": out(home_get, "Wörterbuchwert"),
            "WFEncodeMode": "Encode",
        },
    })
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
        "WFWorkflowActionParameters": {
            "UUID": away_get,
            "WFInput": var("        GefundenesSpiel"),
            "WFDictionaryKey": "away_name",
        },
    })
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.urlencode",
        "WFWorkflowActionParameters": {
            "UUID": away_enc,
            "WFInput": out(away_get, "Wörterbuchwert"),
            "WFEncodeMode": "Encode",
        },
    })

    url = AUTO_ENDPOINT + "?match_id=\ufffc&home=\ufffc&away=\ufffc"
    p1 = url.index("\ufffc")
    p2 = url.index("\ufffc", p1 + 1)
    p3 = url.index("\ufffc", p2 + 1)
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
        "WFWorkflowActionParameters": {
            "UUID": url_text,
            "WFTextActionText": token(url, {
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
            "WFURL": token("\ufffc", {
                "{0, 1}": {"OutputUUID": url_text, "Type": "ActionOutput", "OutputName": "Text"},
            }),
        },
    })
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.setitemname",
        "WFWorkflowActionParameters": {
            "UUID": rename,
            "WFName": token("\ufffc_ForebetDaten.json", {
                "{0, 1}": {"VariableName": "MatchID", "Type": "Variable"},
            }),
            "WFInput": out(download, "Inhalt der URL"),
            "WFDontIncludeFileExtension": False,
        },
    })
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
        "WFWorkflowActionParameters": {
            "UUID": path_text,
            "WFTextActionText": token("\ufffc/\ufffc_ForebetDaten.json", {
                "{0, 1}": {"VariableName": "MatchID", "Type": "Variable"},
                "{2, 1}": {"VariableName": "MatchID", "Type": "Variable"},
            }),
        },
    })
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.documentpicker.save",
        "WFWorkflowActionParameters": {
            "UUID": save,
            "WFInput": out(rename, "Umbenanntes Objekt"),
            "WFAskWhereToSave": False,
            "WFSaveFileOverwrite": True,
            "WFFileDestinationPath": token("\ufffc", {
                "{0, 1}": {"OutputUUID": path_text, "Type": "ActionOutput", "OutputName": "Text"},
            }),
        },
    })

    workflow["WFWorkflowName"] = "FootyStats + Forebet AUTO V4"
    payload = plistlib.dumps(workflow, fmt=plistlib.FMT_BINARY, sort_keys=False)
    OUTPUT_PATH.write_bytes(payload)

    check = plistlib.loads(payload)
    assert len(check["WFWorkflowActions"]) == 98
    assert not any(
        action.get("WFWorkflowActionIdentifier") == "is.workflow.actions.ask"
        and "Forebet:" in str(action.get("WFWorkflowActionParameters", {}).get("WFAskActionPrompt", ""))
        for action in check["WFWorkflowActions"]
    )
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
