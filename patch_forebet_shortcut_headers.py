from __future__ import annotations

import plistlib
from pathlib import Path


PATH = Path(__file__).with_name("FootyStats_Forebet_ELITE_V2_1_unsigned.shortcut")
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 26_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 "
    "Mobile/15E148 Safari/604.1"
)


def _token(text: str):
    return {
        "Value": {"string": text, "attachmentsByRange": {}},
        "WFSerializationType": "WFTextTokenString",
    }


def _headers():
    items = []
    for key, value in (
        ("User-Agent", USER_AGENT),
        ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
        ("Accept-Language", "en-US,en;q=0.9,de;q=0.8"),
        ("Cache-Control", "no-cache"),
    ):
        items.append({
            "WFItemType": 0,
            "WFKey": _token(key),
            "WFValue": _token(value),
        })
    return {
        "Value": {"WFDictionaryFieldValueItems": items},
        "WFSerializationType": "WFDictionaryFieldValue",
    }


def main() -> None:
    workflow = plistlib.loads(PATH.read_bytes())
    actions = workflow.get("WFWorkflowActions") or []

    store_index = next(
        i for i, action in enumerate(actions)
        if action.get("WFWorkflowActionIdentifier") == "is.workflow.actions.setvariable"
        and action.get("WFWorkflowActionParameters", {}).get("WFVariableName") == "ForebetDaten"
    )
    # The Forebet block starts at the MatchDaten -> data read inserted by the
    # ELITE builder. Restricting the scan to this block avoids touching the last
    # FootyStats GET that happens to sit nearby in the workflow.
    start_index = max(
        i for i, action in enumerate(actions[:store_index])
        if action.get("WFWorkflowActionIdentifier") == "is.workflow.actions.getvalueforkey"
        and action.get("WFWorkflowActionParameters", {}).get("WFDictionaryKey") == "data"
        and "MatchDaten" in str(action.get("WFWorkflowActionParameters", {}).get("WFInput"))
    )

    patched = 0
    for action in actions[start_index:store_index]:
        if action.get("WFWorkflowActionIdentifier") != "is.workflow.actions.downloadurl":
            continue
        params = action.setdefault("WFWorkflowActionParameters", {})
        method = str(params.get("WFHTTPMethod") or "GET").upper()
        if method != "GET":
            continue
        params["WFHTTPHeaders"] = _headers()
        params["ShowHeaders"] = True
        patched += 1

    if patched != 2:
        raise SystemExit(f"Expected exactly 2 direct Forebet GET actions, patched={patched}")

    PATH.write_bytes(plistlib.dumps(workflow, fmt=plistlib.FMT_BINARY, sort_keys=False))
    print(f"forebet_direct_gets_with_browser_headers={patched}")
    print("forebet_user_agent=iphone-safari")


if __name__ == "__main__":
    main()
