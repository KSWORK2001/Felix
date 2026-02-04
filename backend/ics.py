import base64
import hashlib
from datetime import datetime, date, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

from dateutil import parser as date_parser


def export_ics(events: List[Dict[str, Any]], tasks: Optional[List[Dict[str, Any]]] = None) -> str:
    try:
        from icalendar import Calendar, Event, Todo
    except Exception as e:
        raise RuntimeError("icalendar package is not installed") from e

    cal = Calendar()
    cal.add("prodid", "-//AI Secretary//")
    cal.add("version", "2.0")

    for e in events:
        ev = Event()
        ev.add("summary", e.get("title") or "(no title)")

        start_dt = _iso_to_dt(e.get("start_iso"))
        end_dt = _iso_to_dt(e.get("end_iso"))
        if start_dt is not None:
            ev.add("dtstart", start_dt)
        if end_dt is not None:
            ev.add("dtend", end_dt)

        uid = _event_uid(e)
        ev.add("uid", uid)

        if e.get("location"):
            ev.add("location", e.get("location"))
        if e.get("notes"):
            ev.add("description", e.get("notes"))

        cal.add_component(ev)

    if tasks:
        for t in tasks:
            td = Todo()
            td.add("summary", t.get("title") or "(no title)")
            uid = _task_uid(t)
            td.add("uid", uid)
            due_dt = _iso_to_dt(t.get("due_iso"))
            if due_dt is not None:
                td.add("due", due_dt)
            if t.get("notes"):
                td.add("description", t.get("notes"))
            status = "COMPLETED" if int(t.get("completed") or 0) == 1 else "NEEDS-ACTION"
            td.add("status", status)
            cal.add_component(td)

    return cal.to_ical().decode("utf-8", errors="replace")


def import_ics(ics_text: str, default_provider: str = "ics") -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    try:
        from icalendar import Calendar
    except Exception as e:
        raise RuntimeError("icalendar package is not installed") from e

    cal = Calendar.from_ical(ics_text)

    events: List[Dict[str, Any]] = []
    tasks: List[Dict[str, Any]] = []

    for comp in cal.walk():
        name = (getattr(comp, "name", "") or "").upper()

        if name == "VEVENT":
            uid = str(comp.get("UID") or "").strip()
            summary = str(comp.get("SUMMARY") or "(no title)")
            dtstart = _ical_dt_to_iso(comp.get("DTSTART"))
            dtend = _ical_dt_to_iso(comp.get("DTEND"))

            if not dtstart:
                continue
            if not dtend:
                dtend = _add_default_duration(dtstart)

            if not uid:
                uid = _hash_fallback_uid(summary, dtstart, dtend)

            events.append(
                {
                    "external_provider": default_provider,
                    "external_id": uid,
                    "title": summary,
                    "start_iso": dtstart,
                    "end_iso": dtend,
                    "location": _opt_str(comp.get("LOCATION")),
                    "notes": _opt_str(comp.get("DESCRIPTION")),
                    "source": default_provider,
                }
            )

        if name == "VTODO":
            uid = str(comp.get("UID") or "").strip()
            summary = str(comp.get("SUMMARY") or "(no title)")
            due_iso = _ical_dt_to_iso(comp.get("DUE"))
            status = str(comp.get("STATUS") or "").upper().strip()
            completed = status == "COMPLETED"

            if not uid:
                uid = _hash_fallback_uid(summary, due_iso or "", status)

            tasks.append(
                {
                    "external_provider": default_provider,
                    "external_id": uid,
                    "title": summary,
                    "due_iso": due_iso,
                    "completed": completed,
                    "notes": _opt_str(comp.get("DESCRIPTION")),
                    "source": default_provider,
                }
            )

    return events, tasks


def _iso_to_dt(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        dt = date_parser.isoparse(str(v))
        if isinstance(dt, datetime):
            return dt
    except Exception:
        return None
    return None


def _ical_dt_to_iso(prop: Any) -> Optional[str]:
    if prop is None:
        return None

    try:
        dt = prop.dt
    except Exception:
        dt = prop

    if isinstance(dt, datetime):
        return dt.isoformat()

    if isinstance(dt, date):
        d = dt
        return datetime(d.year, d.month, d.day, 0, 0, 0).isoformat()

    try:
        parsed = date_parser.parse(str(dt))
        if isinstance(parsed, datetime):
            return parsed.isoformat()
    except Exception:
        return None

    return None


def _add_default_duration(start_iso: str) -> str:
    try:
        dt = date_parser.isoparse(start_iso)
    except Exception:
        return start_iso

    if isinstance(dt, datetime):
        return (dt + timedelta(minutes=60)).isoformat()

    return start_iso


def _hash_fallback_uid(*parts: str) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update((p or "").encode("utf-8", errors="ignore"))
        h.update(b"\n")
    return h.hexdigest()


def _event_uid(e: Dict[str, Any]) -> str:
    prov = (e.get("external_provider") or "").strip()
    ext = (e.get("external_id") or "").strip()
    if prov and ext:
        return f"{prov}:{ext}"

    internal_id = e.get("id")
    if internal_id is not None:
        return f"internal:event:{internal_id}"

    return _hash_fallback_uid(str(e.get("title") or ""), str(e.get("start_iso") or ""), str(e.get("end_iso") or ""))


def _task_uid(t: Dict[str, Any]) -> str:
    prov = (t.get("external_provider") or "").strip()
    ext = (t.get("external_id") or "").strip()
    if prov and ext:
        return f"{prov}:{ext}"

    internal_id = t.get("id")
    if internal_id is not None:
        return f"internal:task:{internal_id}"

    return _hash_fallback_uid(str(t.get("title") or ""), str(t.get("due_iso") or ""))


def _opt_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def text_to_base64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8", errors="replace")).decode("utf-8")


def base64_to_text(b64: str) -> str:
    raw = base64.b64decode(b64)
    return raw.decode("utf-8", errors="replace")
