from datetime import date, datetime, timedelta
import json
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DATA_FILE = Path(__file__).with_name("todo.json")
STORE_LOCK = Lock()

Importance = Literal["low", "medium", "high"]
TaskLabel = Literal["Personal", "Georgia Tech", "Work AT&T", "Work SOCO", "Pookie"]

app = FastAPI(title="Fun Todo API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Schemas ----------
class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    notes: Optional[str] = None
    due_date: Optional[date] = None
    importance: Importance = "medium"
    label: TaskLabel = "Personal"

class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    notes: Optional[str] = None
    due_date: Optional[date] = None
    importance: Optional[Importance] = None
    label: Optional[TaskLabel] = None
    completed: Optional[bool] = None

class TaskOut(BaseModel):
    id: int
    title: str
    notes: Optional[str]
    due_date: Optional[date]
    importance: Importance
    label: TaskLabel
    completed: bool
    completed_at: Optional[datetime]
    created_at: datetime

class StatsOut(BaseModel):
    streak: int
    completed_today: int
    completed_this_week: int

def _initial_store() -> Dict[str, Any]:
    return {"next_id": 1, "tasks": []}


def _load_store() -> Dict[str, Any]:
    if not DATA_FILE.exists():
        data = _initial_store()
        DATA_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data

    raw = DATA_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        return _initial_store()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _initial_store()

    if not isinstance(data, dict):
        return _initial_store()
    if "tasks" not in data or not isinstance(data["tasks"], list):
        data["tasks"] = []
    if "next_id" not in data or not isinstance(data["next_id"], int):
        max_id = max((int(t.get("id", 0)) for t in data["tasks"]), default=0)
        data["next_id"] = max_id + 1
    return data


def _save_store(data: Dict[str, Any]) -> None:
    DATA_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _task_sort_key(task: Dict[str, Any]):
    completed = bool(task.get("completed", False))
    due_raw = task.get("due_date")
    due_key = due_raw if isinstance(due_raw, str) else "9999-12-31"
    created_raw = task.get("created_at")
    try:
        created_dt = datetime.fromisoformat(created_raw) if isinstance(created_raw, str) else datetime.min
    except ValueError:
        created_dt = datetime.min
    return (completed, due_key, -created_dt.timestamp())


def _normalize_task(task: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": int(task["id"]),
        "title": str(task["title"]),
        "notes": task.get("notes"),
        "due_date": task.get("due_date"),
        "importance": task.get("importance", "medium"),
        "label": task.get("label", "Personal"),
        "completed": bool(task.get("completed", False)),
        "completed_at": task.get("completed_at"),
        "created_at": task.get("created_at"),
    }


def _update_payload_dict(payload: TaskUpdate) -> Dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(exclude_unset=True)
    return payload.dict(exclude_unset=True)


def compute_streak(tasks: List[Dict[str, Any]]) -> int:
    today = date.today()
    completed_dates: List[date] = []

    for t in tasks:
        if not t.get("completed"):
            continue
        completed_at = t.get("completed_at")
        if not isinstance(completed_at, str):
            continue
        try:
            completed_dates.append(datetime.fromisoformat(completed_at).date())
        except ValueError:
            continue

    completed_set = set(completed_dates)
    if today not in completed_set:
        return 0

    streak = 0
    cursor = today
    while cursor in completed_set:
        streak += 1
        cursor = cursor - timedelta(days=1)
    return streak

@app.get("/tasks", response_model=List[TaskOut])
def list_tasks(due_date: Optional[date] = None):
    with STORE_LOCK:
        data = _load_store()
        all_tasks = [_normalize_task(t) for t in data["tasks"]]

    if due_date:
        due_str = due_date.isoformat()
        all_tasks = [t for t in all_tasks if t.get("due_date") == due_str]

    all_tasks.sort(key=_task_sort_key)
    return all_tasks

@app.post("/tasks", response_model=TaskOut)
def create_task(payload: TaskCreate):
    with STORE_LOCK:
        data = _load_store()
        task = {
            "id": data["next_id"],
            "title": payload.title.strip(),
            "notes": payload.notes,
            "due_date": payload.due_date.isoformat() if payload.due_date else None,
            "importance": payload.importance,
            "label": payload.label,
            "completed": False,
            "completed_at": None,
            "created_at": datetime.utcnow().isoformat(),
        }
        data["tasks"].append(task)
        data["next_id"] += 1
        _save_store(data)

    return _normalize_task(task)

@app.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, payload: TaskUpdate):
    updates = _update_payload_dict(payload)

    with STORE_LOCK:
        data = _load_store()
        target = None
        for t in data["tasks"]:
            if int(t.get("id", -1)) == task_id:
                target = t
                break

        if target is None:
            raise HTTPException(status_code=404, detail="Task not found")

        if "title" in updates:
            target["title"] = updates["title"].strip() if updates["title"] else target["title"]
        if "notes" in updates:
            target["notes"] = updates["notes"]
        if "due_date" in updates:
            due = updates["due_date"]
            target["due_date"] = due.isoformat() if isinstance(due, date) else None
        if "importance" in updates:
            target["importance"] = updates["importance"]
        if "label" in updates:
            target["label"] = updates["label"]

        if "completed" in updates:
            completed = bool(updates["completed"])
            target["completed"] = completed
            if completed and not target.get("completed_at"):
                target["completed_at"] = datetime.utcnow().isoformat()
            if not completed:
                target["completed_at"] = None

        _save_store(data)

    return _normalize_task(target)

@app.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    with STORE_LOCK:
        data = _load_store()
        before = len(data["tasks"])
        data["tasks"] = [t for t in data["tasks"] if int(t.get("id", -1)) != task_id]
        if len(data["tasks"]) == before:
            raise HTTPException(status_code=404, detail="Task not found")
        _save_store(data)

    return {"ok": True}

@app.get("/stats", response_model=StatsOut)
def stats():
    with STORE_LOCK:
        data = _load_store()
        tasks = [_normalize_task(t) for t in data["tasks"]]

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    completed_today = 0
    completed_week = 0

    for t in tasks:
        if not t.get("completed"):
            continue
        completed_at = t.get("completed_at")
        if not isinstance(completed_at, str):
            continue
        try:
            d = datetime.fromisoformat(completed_at).date()
        except ValueError:
            continue

        if d == today:
            completed_today += 1
        if week_start <= d <= today:
            completed_week += 1

    return StatsOut(
        streak=compute_streak(tasks),
        completed_today=completed_today,
        completed_this_week=completed_week,
    )
