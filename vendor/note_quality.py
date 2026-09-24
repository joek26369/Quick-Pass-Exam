"""Representation-only Cornell normalization extracted for the standalone package."""
from typing import Any


def _text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def normalize_cornell(value: Any) -> dict:
    if not isinstance(value, dict):
        return {"cues": [], "notes": [], "pairs": [], "summary": "", "pairing_status": "empty"}
    raw_pairs = value.get("pairs", value.get("items"))
    pairs = []
    if isinstance(raw_pairs, list) and raw_pairs:
        for item in raw_pairs:
            if not isinstance(item, dict):
                continue
            cue_value = item.get("cue", item.get("question", ""))
            note_value = item.get("note", item.get("answer", ""))
            cue = cue_value.strip() if isinstance(cue_value, str) else ""
            note = note_value.strip() if isinstance(note_value, str) else ""
            if cue or note:
                pairs.append({"cue": cue, "note": note})
        cues = [p["cue"] for p in pairs if p["cue"]]
        notes = [p["note"] for p in pairs if p["note"]]
        status = "paired" if pairs and all(p["cue"] and p["note"] for p in pairs) else "unpaired"
    else:
        cues = _text_list(value.get("cues"))
        notes = _text_list(value.get("notes", value.get("answers")))
        # Equal lengths do not prove semantic correspondence. Preserve the
        # source arrays without inventing cue/answer relationships.
        status = "unpaired" if cues or notes else "empty"

    return {"cues": cues, "notes": notes, "pairs": pairs,
            "summary": str(value.get("summary", "") or ""), "pairing_status": status}
