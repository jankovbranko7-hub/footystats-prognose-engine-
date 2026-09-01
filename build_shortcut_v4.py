import base64
import copy
import plistlib
import re
import uuid
from pathlib import Path


APP_PATH = Path(__file__).with_name("app.py")
OUTPUT_PATH = Path(__file__).with_name("FootyStats + Forebet Export V4.unsigned.shortcut")


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


def main():
    app_text = APP_PATH.read_text()
    encoded = re.search(r'_PREPARED_SHORTCUT_B64 = "([A-Za-z0-9+/=]+)"', app_text).group(1)
    workflow = plistlib.loads(base64.b64decode(encoded))
    actions = workflow["WFWorkflowActions"]

    ask_uuid = new_uuid()
    json_uuid = new_uuid()
    renamed_uuid = new_uuid()
    path_uuid = new_uuid()
    save_uuid = new_uuid()

    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.ask",
        "WFWorkflowActionParameters": {
            "UUID": ask_uuid,
            "WFInputType": "Text",
            "WFAskActionPrompt": "Forebet: 1;X;2;BTTS-Ja;Over-2,5;Tipp;Ø-Tore;URL — Beispiel: 45;28;27;58;61;2-1;2,9;https://www.forebet.com/...",
        },
    })

    json_text = '{"schema":"forebet-manual-v1","match_id":\ufffc,"raw_entry":"\ufffc"}'
    first_placeholder = json_text.index("\ufffc")
    second_placeholder = json_text.index("\ufffc", first_placeholder + 1)
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
        "WFWorkflowActionParameters": {
            "UUID": json_uuid,
            "WFTextActionText": token_string(json_text, {
                f"{{{first_placeholder}, 1}}": {"VariableName": "MatchID", "Type": "Variable"},
                f"{{{second_placeholder}, 1}}": {"OutputUUID": ask_uuid, "Type": "ActionOutput", "OutputName": "Nach Eingabe fragen"},
            }),
        },
    })

    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.setitemname",
        "WFWorkflowActionParameters": {
            "UUID": renamed_uuid,
            "WFDontIncludeFileExtension": False,
            "WFInput": output_attachment(json_uuid, "Text"),
            "WFName": token_string("\ufffc_ForebetDaten.json", {
                "{0, 1}": {"VariableName": "MatchID", "Type": "Variable"},
            }),
        },
    })

    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
        "WFWorkflowActionParameters": {
            "UUID": path_uuid,
            "WFTextActionText": token_string("\ufffc/\ufffc_ForebetDaten.json", {
                "{0, 1}": {"VariableName": "MatchID", "Type": "Variable"},
                "{2, 1}": {"VariableName": "MatchID", "Type": "Variable"},
            }),
        },
    })

    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.documentpicker.save",
        "WFWorkflowActionParameters": {
            "UUID": save_uuid,
            "WFAskWhereToSave": False,
            "WFSaveFileOverwrite": False,
            "WFInput": output_attachment(renamed_uuid, "Umbenanntes Objekt"),
            "WFFileDestinationPath": output_attachment(path_uuid, "Text"),
        },
    })

    workflow["WFWorkflowName"] = "FootyStats + Forebet Export V4"
    payload = plistlib.dumps(workflow, fmt=plistlib.FMT_BINARY, sort_keys=False)
    OUTPUT_PATH.write_bytes(payload)
    print(base64.b64encode(payload).decode("ascii"))


if __name__ == "__main__":
    main()
