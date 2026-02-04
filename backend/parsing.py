import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from dateutil import parser as date_parser


@dataclass
class AssistantAction:
    tool: str
    args: Dict[str, Any]


def _safe_parse_datetime(text: str, default_dt: datetime) -> Optional[datetime]:
    try:
        dt = date_parser.parse(text, fuzzy=True, default=default_dt)
        return dt
    except Exception:
        return None


def parse_user_command(message: str, now: datetime) -> Tuple[str, List[AssistantAction]]:
    m = message.strip()
    lower = m.lower()

    if any(k in lower for k in ["update", "edit", "reschedule", "move"]):
        id_match = re.search(r"\b(\d+)\b", lower)
        if id_match:
            item_id = int(id_match.group(1))

            if any(k in lower for k in ["task", "todo", "to do"]):
                title_match = re.search(r"\bto\b\s+(.+)$", m, flags=re.IGNORECASE)
                title = title_match.group(1).strip() if title_match else None
                due_dt = _safe_parse_datetime(m, now)
                due_iso = due_dt.isoformat() if due_dt else None

                return (
                    "update_task",
                    [
                        AssistantAction(
                            tool="update_task",
                            args={
                                "task_id": item_id,
                                "title": title,
                                "due_iso": due_iso,
                            },
                        )
                    ],
                )

            dt = _safe_parse_datetime(m, now)
            start_iso = dt.isoformat() if dt else None

            duration_minutes = 60
            dur_match = re.search(r"(\d+)\s*(min|mins|minute|minutes|hr|hrs|hour|hours)", lower)
            if dur_match:
                n = int(dur_match.group(1))
                unit = dur_match.group(2)
                if unit.startswith("h"):
                    duration_minutes = n * 60
                else:
                    duration_minutes = n

            end_iso = None
            if dt is not None:
                end_iso = (dt + timedelta(minutes=duration_minutes)).isoformat()

            title_match = re.search(r"\bto\b\s+(.+)$", m, flags=re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else None

            return (
                "update_event",
                [
                    AssistantAction(
                        tool="update_event",
                        args={
                            "event_id": item_id,
                            "title": title,
                            "start_iso": start_iso,
                            "end_iso": end_iso,
                        },
                    )
                ],
            )

    if any(k in lower for k in ["what's on", "whats on", "today", "my day", "agenda"]):
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return (
            "agenda",
            [
                AssistantAction(
                    tool="get_agenda",
                    args={"start_iso": start.isoformat(), "end_iso": end.isoformat()},
                )
            ],
        )

    if any(k in lower for k in ["add", "create", "schedule", "set up"]):
        is_task = any(k in lower for k in ["task", "todo", "to do", "remind me", "reminder"])
        is_event = ("event" in lower) or ("meeting" in lower) or ("calendar" in lower) or (not is_task)

        if is_task and not is_event:
            title = re.sub(r"\b(add|create)\b", "", m, flags=re.IGNORECASE).strip()
            due_dt = _safe_parse_datetime(m, now)
            due_iso = due_dt.isoformat() if due_dt else None
            if not title:
                title = "New task"
            return (
                "add_task",
                [AssistantAction(tool="add_task", args={"title": title, "due_iso": due_iso})],
            )

        title = m
        title = re.sub(r"\b(add|create|schedule|set up)\b", "", title, flags=re.IGNORECASE).strip()
        title = re.sub(r"\b(event|meeting|calendar)\b", "", title, flags=re.IGNORECASE).strip()
        if not title:
            title = "New event"

        start_dt = _safe_parse_datetime(m, now)
        if start_dt is None:
            start_dt = now + timedelta(minutes=5)

        duration_minutes = 60
        dur_match = re.search(r"(\d+)\s*(min|mins|minute|minutes|hr|hrs|hour|hours)", lower)
        if dur_match:
            n = int(dur_match.group(1))
            unit = dur_match.group(2)
            if unit.startswith("h"):
                duration_minutes = n * 60
            else:
                duration_minutes = n

        end_dt = start_dt + timedelta(minutes=duration_minutes)

        return (
            "add_event",
            [
                AssistantAction(
                    tool="add_event",
                    args={
                        "title": title,
                        "start_iso": start_dt.isoformat(),
                        "end_iso": end_dt.isoformat(),
                    },
                )
            ],
        )

    if any(k in lower for k in ["complete task", "mark done", "done task"]):
        id_match = re.search(r"\b(\d+)\b", lower)
        if id_match:
            return (
                "complete_task",
                [AssistantAction(tool="update_task", args={"task_id": int(id_match.group(1)), "completed": True})],
            )
        return ("none", [])

    if any(k in lower for k in ["delete", "remove", "cancel"]):
        id_match = re.search(r"\b(\d+)\b", lower)
        if id_match:
            if any(k in lower for k in ["task", "todo", "to do"]):
                return (
                    "delete_task",
                    [AssistantAction(tool="delete_task", args={"task_id": int(id_match.group(1))})],
                )
            return (
                "delete_event",
                [AssistantAction(tool="delete_event", args={"event_id": int(id_match.group(1))})],
            )
        return ("none", [])

    return ("none", [])


_time_re = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.IGNORECASE)


def parse_calendar_ocr_text(text: str, reference_date: datetime) -> List[Dict[str, Any]]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    items: List[Dict[str, Any]] = []

    current_date = reference_date.date()

    for ln in lines:
        dt = _extract_time_on_date(ln, current_date)
        if dt is None:
            continue

        title = _guess_title_after_time(ln)
        if not title:
            continue

        start_dt = dt
        end_dt = start_dt + timedelta(minutes=30)

        items.append(
            {
                "title": title,
                "start_iso": start_dt.isoformat(),
                "end_iso": end_dt.isoformat(),
                "source": "screenshot_ocr",
            }
        )

    return _dedupe_events(items)


def _extract_time_on_date(line: str, d) -> Optional[datetime]:
    m = _time_re.search(line)
    if not m:
        return None

    hour = int(m.group(1))
    minute = int(m.group(2) or "0")
    ampm = (m.group(3) or "").lower().strip()

    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0

    try:
        return datetime(d.year, d.month, d.day, hour, minute)
    except Exception:
        return None


def _guess_title_after_time(line: str) -> str:
    m = _time_re.search(line)
    if not m:
        return ""

    rest = line[m.end() :].strip(" -–—:\t")
    rest = re.sub(r"\s+", " ", rest).strip()

    if len(rest) < 2:
        return ""

    rest = re.sub(r"\b(am|pm)\b", "", rest, flags=re.IGNORECASE).strip(" -–—:\t")
    return rest


def _dedupe_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for e in events:
        key = (e.get("title"), e.get("start_iso"))
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out
