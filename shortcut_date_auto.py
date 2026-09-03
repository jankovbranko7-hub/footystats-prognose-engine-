from __future__ import annotations

import copy
import plistlib
import uuid
from typing import Any, Dict


PRODUCT_NAME = "FootyStats + Forebet ELITE PICKS"
DATE_ASK_UUID = "BD34DEEF-AD61-42EE-A348-AA244E6DEEFE"
DATE_ASK_OUTPUT_NAME = "Nach Eingabe fragen"


def _uuid() -> str:
    return str(uuid.uuid4()).upper()


def _token_string(text: str, attachments: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "Value": {"string": text, "attachmentsByRange": attachments},
        "WFSerializationType": "WFTextTokenString",
    }


def _output_attachment(output_uuid: str, output_name: str) -> Dict[str, Any]:
    return {
        "Value": {
            "OutputUUID": output_uuid,
            "Type": "ActionOutput",
            "OutputName": output_name,
        },
        "WFSerializationType": "WFTextTokenAttachment",
    }


def _variable_attachment(name: str) -> Dict[str, Any]:
    return {
        "Value": {"VariableName": name, "Type": "Variable"},
        "WFSerializationType": "WFTextTokenAttachment",
    }


def _forebet_actions(base_url: str) -> list[Dict[str, Any]]:
    home_get = _uuid()
    home_enc = _uuid()
    away_get = _uuid()
    away_enc = _uuid()
    url_text = _uuid()
    download = _uuid()
    store = _uuid()

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
                "UUID": home_get,
                "WFInput": _variable_attachment("        GefundenesSpiel"),
                "WFDictionaryKey": "home_name",
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.urlencode",
            "WFWorkflowActionParameters": {
                "UUID": home_enc,
                "WFInput": _output_attachment(home_get, "Wörterbuchwert"),
                "WFEncodeMode": "Encode",
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
            "WFWorkflowActionParameters": {
                "UUID": away_get,
                "WFInput": _variable_attachment("        GefundenesSpiel"),
                "WFDictionaryKey": "away_name",
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.urlencode",
            "WFWorkflowActionParameters": {
                "UUID": away_enc,
                "WFInput": _output_attachment(away_get, "Wörterbuchwert"),
                "WFEncodeMode": "Encode",
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
            "WFWorkflowActionParameters": {
                "UUID": url_text,
                "WFTextActionText": _token_string(
                    template,
                    {
                        f"{{{positions[0]}, 1}}": {"VariableName": "MatchID", "Type": "Variable"},
                        f"{{{positions[1]}, 1}}": {"OutputUUID": home_enc, "Type": "ActionOutput", "OutputName": "URL Encoded Text"},
                        f"{{{positions[2]}, 1}}": {"OutputUUID": away_enc, "Type": "ActionOutput", "OutputName": "URL Encoded Text"},
                        f"{{{positions[3]}, 1}}": {"OutputUUID": DATE_ASK_UUID, "Type": "ActionOutput", "OutputName": DATE_ASK_OUTPUT_NAME},
                    },
                ),
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
            "WFWorkflowActionParameters": {
                "UUID": download,
                "WFURL": _token_string(
                    "\ufffc",
                    {"{0, 1}": {"OutputUUID": url_text, "Type": "ActionOutput", "OutputName": "Text"}},
                ),
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.setvariable",
            "WFWorkflowActionParameters": {
                "UUID": store,
                "WFInput": _output_attachment(download, "Inhalt der URL"),
                "WFVariableName": "ForebetDaten",
            },
        },
    ]


def _json_variable_item(key: str, variable: str) -> Dict[str, Any]:
    return {
        "WFItemType": 0,
        "WFKey": _token_string(key, {}),
        "WFValue": _token_string(
            "\ufffc",
            {"{0, 1}": {"VariableName": variable, "Type": "Variable"}},
        ),
    }


def _analysis_actions(base_url: str) -> list[Dict[str, Any]]:
    download = _uuid()
    decision = _uuid()
    conditional = _uuid()
    archive = _uuid()
    rename = _uuid()
    path_text = _uuid()
    save = _uuid()

    return [
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
            "WFWorkflowActionParameters": {
                "UUID": download,
                "WFURL": _token_string(base_url.rstrip("/") + "/api/elite-candidate", {}),
                "WFHTTPMethod": "POST",
                "WFHTTPBodyType": "JSON",
                "WFJSONValues": {
                    "Value": {
                        "WFDictionaryFieldValueItems": [
                            _json_variable_item("matchData", "MatchDaten"),
                            _json_variable_item("leagueData", "LeagueDatenFinal"),
                            _json_variable_item("formData", "FormDatenFinal"),
                            _json_variable_item("tableData", "TableDatenFinal"),
                            _json_variable_item("playerData", "PlayerDatenFinal"),
                            _json_variable_item("forebetData", "ForebetDaten"),
                        ],
                    },
                    "WFSerializationType": "WFDictionaryFieldValue",
                },
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
            "WFWorkflowActionParameters": {
                "UUID": decision,
                "WFInput": _output_attachment(download, "Inhalt der URL"),
                "WFDictionaryKey": "decision",
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.conditional",
            "WFWorkflowActionParameters": {
                "GroupingIdentifier": conditional,
                "WFControlFlowMode": 0,
                "WFCondition": 4,
                "WFConditionalActionString": "SPIELEN",
                "WFInput": _output_attachment(decision, "Wörterbuchwert"),
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
            "WFWorkflowActionParameters": {
                "UUID": archive,
                "WFInput": _output_attachment(download, "Inhalt der URL"),
                "WFDictionaryKey": "archive",
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.setitemname",
            "WFWorkflowActionParameters": {
                "UUID": rename,
                "WFName": _token_string(
                    "\ufffc_ELITE_Analyse.json",
                    {"{0, 1}": {"VariableName": "MatchID", "Type": "Variable"}},
                ),
                "WFInput": _output_attachment(archive, "Wörterbuchwert"),
                "WFDontIncludeFileExtension": False,
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
            "WFWorkflowActionParameters": {
                "UUID": path_text,
                "WFTextActionText": _token_string(
                    "FootyStats_ELITE/\ufffc/\ufffc_ELITE_Analyse.json",
                    {
                        "{16, 1}": {
                            "OutputUUID": DATE_ASK_UUID,
                            "Type": "ActionOutput",
                            "OutputName": DATE_ASK_OUTPUT_NAME,
                        },
                        "{18, 1}": {"VariableName": "MatchID", "Type": "Variable"},
                    },
                ),
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.documentpicker.save",
            "WFWorkflowActionParameters": {
                "UUID": save,
                "WFInput": _output_attachment(rename, "Umbenanntes Objekt"),
                "WFAskWhereToSave": False,
                "WFSaveFileOverwrite": True,
                "WFFileDestinationPath": _token_string(
                    "\ufffc",
                    {"{0, 1}": {"OutputUUID": path_text, "Type": "ActionOutput", "OutputName": "Text"}},
                ),
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.conditional",
            "WFWorkflowActionParameters": {
                "UUID": _uuid(),
                "GroupingIdentifier": conditional,
                "WFControlFlowMode": 2,
            },
        },
    ]


def _result_folder_action() -> Dict[str, Any]:
    return {
        "WFWorkflowActionIdentifier": "is.workflow.actions.file.createfolder",
        "WFWorkflowActionParameters": {
            "UUID": _uuid(),
            "WFFilePath": _token_string(
                "FootyStats_ELITE/\ufffc",
                {
                    "{16, 1}": {
                        "OutputUUID": DATE_ASK_UUID,
                        "Type": "ActionOutput",
                        "OutputName": DATE_ASK_OUTPUT_NAME,
                    },
                },
            ),
        },
    }


def build_date_auto_shortcut(base_shortcut: bytes, base_url: str) -> bytes:
    """Convert the stable V2 export into a date-only ELITE selection workflow.

    The FootyStats API key remains an installation question. During a run the only
    user input is the date. Every fixture is checked, but only SPIELEN candidates
    are saved, with all six sources and the analysis in one JSON archive.
    """
    if not base_url.startswith("https://"):
        raise ValueError("Die öffentliche AUTO-URL muss HTTPS verwenden.")
    workflow = plistlib.loads(base_shortcut)
    source_actions = workflow.get("WFWorkflowActions") or []
    if not source_actions:
        raise ValueError("Der Basis-Kurzbefehl enthält keine Aktionen.")

    date_questions = [
        action for action in source_actions
        if action.get("WFWorkflowActionIdentifier") == "is.workflow.actions.ask"
        and action.get("WFWorkflowActionParameters", {}).get("UUID") == DATE_ASK_UUID
    ]
    if len(date_questions) != 1:
        raise ValueError("Der eindeutige Datumsschritt des V2-Kurzbefehls fehlt.")

    games_set_index = next(
        index for index, action in enumerate(source_actions)
        if action.get("WFWorkflowActionIdentifier") == "is.workflow.actions.setvariable"
        and action.get("WFWorkflowActionParameters", {}).get("WFVariableName") == "SpieleDaten"
    )
    selected_set_index = next(
        index for index, action in enumerate(source_actions)
        if action.get("WFWorkflowActionIdentifier") == "is.workflow.actions.setvariable"
        and str(action.get("WFWorkflowActionParameters", {}).get("WFVariableName", "")).strip() == "GefundenesSpiel"
    )
    if selected_set_index <= games_set_index:
        raise ValueError("Der Einzelspielblock des V2-Kurzbefehls ist nicht eindeutig.")

    prefix = copy.deepcopy(source_actions[: games_set_index + 1])
    body = copy.deepcopy(source_actions[selected_set_index + 1 :])

    # A daily outer loop must start these collectors anew for every match. The
    # original single-match shortcut used Append because it ran only once.
    reset_on_first_append = {"LeagueSeiten", "FormTeams", "PlayerSeiten"}
    reset_done: set[str] = set()
    data_variables = {
        "LeagueDaten": "LeagueDatenFinal",
        "MatchDaten": "MatchDaten",
        "FormDaten": "FormDatenFinal",
        "TableDaten": "TableDatenFinal",
        "PlayerDaten": "PlayerDatenFinal",
    }
    captured_data: set[str] = set()
    cleaned_body: list[Dict[str, Any]] = []
    for action in body:
        identifier = action.get("WFWorkflowActionIdentifier")
        parameters = action.setdefault("WFWorkflowActionParameters", {})
        if identifier == "is.workflow.actions.showresult":
            continue
        if identifier in {"is.workflow.actions.documentpicker.save", "is.workflow.actions.file.createfolder"}:
            continue
        if identifier == "is.workflow.actions.gettext" and any(
            f"{marker}.json" in str(parameters) for marker in data_variables
        ):
            # These Text actions only built the former per-source save paths.
            continue
        if identifier == "is.workflow.actions.setitemname":
            serialized_name = str(parameters.get("WFName") or "")
            marker = next((name for name in data_variables if name in serialized_name), None)
            if marker is None:
                continue
            cleaned_body.append({
                "WFWorkflowActionIdentifier": "is.workflow.actions.setvariable",
                "WFWorkflowActionParameters": {
                    "UUID": _uuid(),
                    "WFInput": parameters.get("WFInput"),
                    "WFVariableName": data_variables[marker],
                },
            })
            captured_data.add(marker)
            continue
        if identifier == "is.workflow.actions.appendvariable":
            variable = parameters.get("WFVariableName")
            if variable in reset_on_first_append and variable not in reset_done:
                action["WFWorkflowActionIdentifier"] = "is.workflow.actions.setvariable"
                reset_done.add(variable)
        cleaned_body.append(action)
    if reset_done != reset_on_first_append:
        raise ValueError("Nicht alle Seitensammler konnten für den Tageslauf zurückgesetzt werden.")
    if captured_data != set(data_variables):
        missing = sorted(set(data_variables) - captured_data)
        raise ValueError(f"Nicht alle fünf FootyStats-Datenblöcke wurden erfasst: {missing}")

    grouping = _uuid()
    repeat_start = {
        "WFWorkflowActionIdentifier": "is.workflow.actions.repeat.each",
        "WFWorkflowActionParameters": {
            "WFInput": _variable_attachment("SpieleDaten"),
            "GroupingIdentifier": grouping,
            "WFControlFlowMode": 0,
        },
    }
    set_match = {
        "WFWorkflowActionIdentifier": "is.workflow.actions.setvariable",
        "WFWorkflowActionParameters": {
            "UUID": _uuid(),
            "WFInput": _variable_attachment("Repeat Item"),
            "WFVariableName": "        GefundenesSpiel",
        },
    }
    repeat_end = {
        "WFWorkflowActionIdentifier": "is.workflow.actions.repeat.each",
        "WFWorkflowActionParameters": {
            "UUID": _uuid(),
            "GroupingIdentifier": grouping,
            "WFControlFlowMode": 2,
        },
    }

    actions = (
        prefix
        + [_result_folder_action(), repeat_start, set_match]
        + cleaned_body
        + _forebet_actions(base_url)
        + _analysis_actions(base_url)
        + [repeat_end]
    )
    workflow["WFWorkflowActions"] = actions
    workflow["WFWorkflowName"] = PRODUCT_NAME
    payload = plistlib.dumps(workflow, fmt=plistlib.FMT_BINARY, sort_keys=False)

    verified = plistlib.loads(payload)
    identifiers = [action.get("WFWorkflowActionIdentifier") for action in verified["WFWorkflowActions"]]
    if "is.workflow.actions.choosefromlist" in identifiers:
        raise ValueError("Die Spielauswahl wurde nicht vollständig entfernt.")
    if sum(identifier == "is.workflow.actions.ask" for identifier in identifiers) != 1:
        raise ValueError("Der Kurzbefehl darf während des Laufs nur nach dem Datum fragen.")
    serialized = str(verified)
    if "api/forebet-auto/export" not in serialized:
        raise ValueError("Der automatische Forebet-Export fehlt.")
    if "api/elite-candidate" not in serialized:
        raise ValueError("Die automatische ELITE-Auswahl fehlt.")
    if identifiers.count("is.workflow.actions.documentpicker.save") != 1:
        raise ValueError("Der Kurzbefehl darf pro qualifiziertem Spiel nur ein gemeinsames Archiv speichern.")
    if identifiers.count("is.workflow.actions.conditional") != 2:
        raise ValueError("Die SPIELEN-Speichersperre fehlt.")
    if any(f"_{marker}.json" in serialized for marker in data_variables):
        raise ValueError("Ein alter Einzeldatei-Export ist noch vorhanden.")
    if any("Forebet:" in str(action) for action in verified["WFWorkflowActions"]):
        raise ValueError("Eine manuelle Forebet-Eingabe ist noch vorhanden.")
    return payload
