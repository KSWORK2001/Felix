import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from dateutil import parser as date_parser


def token_path(base_dir: str) -> str:
    return os.path.join(base_dir, "data", "google_token.json")


def load_credentials(base_dir: str):
    tp = token_path(base_dir)
    if not os.path.exists(tp):
        return None

    from google.oauth2.credentials import Credentials

    with open(tp, "r", encoding="utf-8") as f:
        data = f.read()

    try:
        info = eval_json(data)
    except Exception:
        return None

    return Credentials.from_authorized_user_info(info)


def save_credentials(base_dir: str, creds) -> None:
    tp = token_path(base_dir)
    os.makedirs(os.path.dirname(tp), exist_ok=True)
    with open(tp, "w", encoding="utf-8") as f:
        f.write(creds.to_json())


def ensure_valid_credentials(base_dir: str, client_secrets_path: str):
    creds = load_credentials(base_dir)

    if creds is not None:
        if getattr(creds, "expired", False) and getattr(creds, "refresh_token", None):
            from google.auth.transport.requests import Request

            creds.refresh(Request())
            save_credentials(base_dir, creds)
        return creds

    if not client_secrets_path or not os.path.exists(client_secrets_path):
        raise RuntimeError("Google client secrets file path is missing or invalid")

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(
        client_secrets_path,
        scopes=["https://www.googleapis.com/auth/calendar.readonly"],
    )

    creds = flow.run_local_server(port=0)
    save_credentials(base_dir, creds)
    return creds


def connect(base_dir: str, client_secrets_path: str) -> Dict[str, Any]:
    ensure_valid_credentials(base_dir, client_secrets_path)
    return {"ok": True}


def _parse_google_dt(dt_obj: Dict[str, str]) -> Tuple[datetime, bool]:
    if "dateTime" in dt_obj:
        dt = date_parser.isoparse(dt_obj["dateTime"])
        return dt, False

    if "date" in dt_obj:
        d = date_parser.isoparse(dt_obj["date"]).date()
        dt = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)
        return dt, True

    raise ValueError("Invalid date object")


def _to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat()
    return dt.isoformat()


def sync_events(
    base_dir: str,
    client_secrets_path: str,
    time_min: Optional[datetime] = None,
    time_max: Optional[datetime] = None,
    calendar_id: str = "primary",
) -> List[Dict[str, Any]]:
    creds = ensure_valid_credentials(base_dir, client_secrets_path)

    from googleapiclient.discovery import build

    service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    now = datetime.now(timezone.utc)
    if time_min is None:
        time_min = now - timedelta(days=30)
    if time_max is None:
        time_max = now + timedelta(days=90)

    page_token = None
    out: List[Dict[str, Any]] = []

    while True:
        resp = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=_to_iso(time_min),
                timeMax=_to_iso(time_max),
                singleEvents=True,
                orderBy="startTime",
                showDeleted=False,
                pageToken=page_token,
                maxResults=2500,
            )
            .execute()
        )

        items = resp.get("items", []) or []
        for e in items:
            external_id = e.get("id")
            if not external_id:
                continue

            summary = e.get("summary") or "(no title)"
            start_dt, start_is_all_day = _parse_google_dt(e.get("start") or {})
            end_dt, end_is_all_day = _parse_google_dt(e.get("end") or {})

            if start_is_all_day and end_is_all_day:
                pass

            out.append(
                {
                    "external_provider": "google",
                    "external_id": external_id,
                    "external_calendar_id": calendar_id,
                    "title": summary,
                    "start_iso": _to_iso(start_dt),
                    "end_iso": _to_iso(end_dt),
                    "location": e.get("location"),
                    "notes": (e.get("description") or "").strip() or None,
                    "source": "google",
                }
            )

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return out


def eval_json(s: str) -> Dict[str, Any]:
    import json

    return json.loads(s)
