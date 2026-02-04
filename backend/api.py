from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.assistant import Assistant
from backend.db import Database
from backend.llm import GemmaProvider, OpenAiProvider, build_system_prompt
from backend.ocr import ocr_image_base64
from backend.parsing import AssistantAction, parse_calendar_ocr_text, parse_user_command
from backend.settings import AppSettings, SettingsStore
from backend import google_calendar
from backend import ics


class Api:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.db = Database(db_path=self._db_path())
        self.assistant = Assistant(db=self.db, base_dir=base_dir)
        self.settings_store = SettingsStore(base_dir=base_dir)
        self.settings = self.settings_store.load()
        self._gemma_provider = None
        self._openai_provider = None
        self._conversation_history: list = []

    def _db_path(self) -> str:
        import os

        return os.path.join(self.base_dir, "data", "app.db")

    def get_state(self) -> Dict[str, Any]:
        return {"tasks": self.db.list_tasks(), "events": self.db.list_events()}

    def get_settings(self) -> Dict[str, Any]:
        s = self.settings_store.load()
        self.settings = s
        return {
            "provider": s.provider,
            "gemma_model_id": s.gemma_model_id,
            "openai_model": s.openai_model,
            "openai_api_key_present": bool((s.openai_api_key or "").strip()),
            "google_client_secrets_path": s.google_client_secrets_path,
            "google_connected": google_calendar.load_credentials(self.base_dir) is not None,
            "ics_url": s.ics_url,
        }

    def clear_conversation(self) -> Dict[str, Any]:
        self._conversation_history = []
        return {"ok": True}

    def update_settings(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(patch, dict):
            return {"ok": False}

        s = self.settings_store.load()

        clean: Dict[str, Any] = {}
        if "provider" in patch and isinstance(patch["provider"], str):
            clean["provider"] = patch["provider"]
        if "gemma_model_id" in patch and isinstance(patch["gemma_model_id"], str):
            clean["gemma_model_id"] = patch["gemma_model_id"]
        if "openai_model" in patch and isinstance(patch["openai_model"], str):
            clean["openai_model"] = patch["openai_model"]
        if "openai_api_key" in patch and isinstance(patch["openai_api_key"], str):
            clean["openai_api_key"] = patch["openai_api_key"]
        if "google_client_secrets_path" in patch and isinstance(patch["google_client_secrets_path"], str):
            clean["google_client_secrets_path"] = patch["google_client_secrets_path"]
        if "ics_url" in patch and isinstance(patch["ics_url"], str):
            clean["ics_url"] = patch["ics_url"]

        s = self.settings_store.update(clean)
        self.settings = s
        if "gemma_model_id" in clean:
            self._gemma_provider = None
        if "openai_api_key" in clean or "openai_model" in clean:
            self._openai_provider = None

        return {"ok": True, "settings": self.get_settings()}

    def ics_url_sync(self) -> Dict[str, Any]:
        s = self.settings_store.load()
        url = (s.ics_url or "").strip()
        if not url.lower().startswith("http"):
            raise RuntimeError("ICS URL is missing")

        ics_text = self._fetch_text(url)

        imported_events, imported_tasks = ics.import_ics(ics_text, default_provider="ics")
        now_iso = datetime.now().isoformat()

        event_ids: List[int] = []
        for e in imported_events:
            event_ids.append(
                self.db.upsert_external_event(
                    external_provider=e["external_provider"],
                    external_id=e["external_id"],
                    external_calendar_id=e.get("external_calendar_id"),
                    title=e["title"],
                    start_iso=e["start_iso"],
                    end_iso=e["end_iso"],
                    location=e.get("location"),
                    notes=e.get("notes"),
                    source=e.get("source") or "ics",
                    now_iso=now_iso,
                )
            )

        task_ids: List[int] = []
        for t in imported_tasks:
            task_ids.append(
                self.db.upsert_external_task(
                    external_provider=t["external_provider"],
                    external_id=t["external_id"],
                    external_list_id=t.get("external_list_id"),
                    title=t["title"],
                    due_iso=t.get("due_iso"),
                    completed=bool(t.get("completed")),
                    notes=t.get("notes"),
                    now_iso=now_iso,
                )
            )

        return {
            "ok": True,
            "imported_events": len(imported_events),
            "imported_tasks": len(imported_tasks),
            "state": self.get_state(),
        }

    def _fetch_text(self, url: str) -> str:
        import urllib.request

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "AISecretary/1.0"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
        return raw.decode("utf-8", errors="replace")

    def google_connect(self) -> Dict[str, Any]:
        s = self.settings_store.load()
        google_calendar.connect(base_dir=self.base_dir, client_secrets_path=s.google_client_secrets_path)
        return {"ok": True, "settings": self.get_settings()}

    def google_sync(self) -> Dict[str, Any]:
        s = self.settings_store.load()
        events = google_calendar.sync_events(base_dir=self.base_dir, client_secrets_path=s.google_client_secrets_path)
        now_iso = datetime.now().isoformat()

        upserted_ids: List[int] = []
        for e in events:
            upserted_ids.append(
                self.db.upsert_external_event(
                    external_provider=e["external_provider"],
                    external_id=e["external_id"],
                    external_calendar_id=e.get("external_calendar_id"),
                    title=e["title"],
                    start_iso=e["start_iso"],
                    end_iso=e["end_iso"],
                    location=e.get("location"),
                    notes=e.get("notes"),
                    source=e.get("source") or "google",
                    now_iso=now_iso,
                )
            )

        return {"ok": True, "synced": len(events), "event_ids": upserted_ids[:200], "state": self.get_state(), "settings": self.get_settings()}

    def export_ics(self) -> Dict[str, Any]:
        state = self.get_state()
        ics_text = ics.export_ics(events=state.get("events") or [], tasks=state.get("tasks") or [])
        return {
            "ok": True,
            "filename": "ai-secretary.ics",
            "ics_base64": ics.text_to_base64(ics_text),
        }

    def import_ics(self, ics_base64: str) -> Dict[str, Any]:
        ics_text = ics.base64_to_text(ics_base64)
        imported_events, imported_tasks = ics.import_ics(ics_text, default_provider="ics")

        now_iso = datetime.now().isoformat()

        event_ids: List[int] = []
        for e in imported_events:
            ext_id = e.get("external_id")
            if isinstance(ext_id, str) and ext_id.startswith("internal:event:"):
                try:
                    internal_id = int(ext_id.split(":")[-1])
                    self.db.update_event(
                        event_id=internal_id,
                        title=e.get("title"),
                        start_iso=e.get("start_iso"),
                        end_iso=e.get("end_iso"),
                        location=e.get("location"),
                        notes=e.get("notes"),
                        now_iso=now_iso,
                    )
                    event_ids.append(internal_id)
                    continue
                except Exception:
                    pass

            event_ids.append(
                self.db.upsert_external_event(
                    external_provider=e["external_provider"],
                    external_id=e["external_id"],
                    external_calendar_id=e.get("external_calendar_id"),
                    title=e["title"],
                    start_iso=e["start_iso"],
                    end_iso=e["end_iso"],
                    location=e.get("location"),
                    notes=e.get("notes"),
                    source=e.get("source") or "ics",
                    now_iso=now_iso,
                )
            )

        task_ids: List[int] = []
        for t in imported_tasks:
            ext_id = t.get("external_id")
            if isinstance(ext_id, str) and ext_id.startswith("internal:task:"):
                try:
                    internal_id = int(ext_id.split(":")[-1])
                    self.db.update_task(
                        task_id=internal_id,
                        title=t.get("title"),
                        due_iso=t.get("due_iso"),
                        completed=t.get("completed"),
                        notes=t.get("notes"),
                        now_iso=now_iso,
                    )
                    task_ids.append(internal_id)
                    continue
                except Exception:
                    pass

            task_ids.append(
                self.db.upsert_external_task(
                    external_provider=t["external_provider"],
                    external_id=t["external_id"],
                    external_list_id=t.get("external_list_id"),
                    title=t["title"],
                    due_iso=t.get("due_iso"),
                    completed=bool(t.get("completed")),
                    notes=t.get("notes"),
                    now_iso=now_iso,
                )
            )

        return {
            "ok": True,
            "imported_events": len(imported_events),
            "imported_tasks": len(imported_tasks),
            "event_ids": event_ids[:200],
            "task_ids": task_ids[:200],
            "state": self.get_state(),
        }

    def add_task(self, title: str, due_iso: Optional[str] = None, notes: Optional[str] = None) -> Dict[str, Any]:
        now_iso = datetime.now().isoformat()
        task_id = self.db.add_task(title=title, due_iso=due_iso, notes=notes, now_iso=now_iso)
        return {"ok": True, "task_id": task_id, "state": self.get_state()}

    def update_task(
        self,
        task_id: int,
        title: Optional[str] = None,
        due_iso: Optional[str] = None,
        completed: Optional[bool] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        now_iso = datetime.now().isoformat()
        self.db.update_task(task_id=task_id, title=title, due_iso=due_iso, completed=completed, notes=notes, now_iso=now_iso)
        return {"ok": True, "state": self.get_state()}

    def delete_task(self, task_id: int) -> Dict[str, Any]:
        self.db.delete_task(task_id)
        return {"ok": True, "state": self.get_state()}

    def add_event(
        self,
        title: str,
        start_iso: str,
        end_iso: str,
        location: Optional[str] = None,
        notes: Optional[str] = None,
        source: Optional[str] = None,
    ) -> Dict[str, Any]:
        now_iso = datetime.now().isoformat()
        event_id = self.db.add_event(
            title=title,
            start_iso=start_iso,
            end_iso=end_iso,
            location=location,
            notes=notes,
            source=source,
            now_iso=now_iso,
        )
        return {"ok": True, "event_id": event_id, "state": self.get_state()}

    def update_event(
        self,
        event_id: int,
        title: Optional[str] = None,
        start_iso: Optional[str] = None,
        end_iso: Optional[str] = None,
        location: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        now_iso = datetime.now().isoformat()
        self.db.update_event(
            event_id=event_id,
            title=title,
            start_iso=start_iso,
            end_iso=end_iso,
            location=location,
            notes=notes,
            now_iso=now_iso,
        )
        return {"ok": True, "state": self.get_state()}

    def delete_event(self, event_id: int) -> Dict[str, Any]:
        self.db.delete_event(event_id)
        return {"ok": True, "state": self.get_state()}

    def import_calendar_screenshot(self, image_base64: str) -> Dict[str, Any]:
        now = datetime.now()
        ocr_text = ocr_image_base64(image_base64)
        parsed = parse_calendar_ocr_text(ocr_text, reference_date=now)

        created_ids: List[int] = []
        now_iso = now.isoformat()
        for e in parsed:
            created_ids.append(
                self.db.add_event(
                    title=e["title"],
                    start_iso=e["start_iso"],
                    end_iso=e["end_iso"],
                    location=None,
                    notes=None,
                    source=e.get("source"),
                    now_iso=now_iso,
                )
            )

        return {
            "ok": True,
            "created_event_ids": created_ids,
            "ocr_preview": ocr_text[:2000],
            "parsed_count": len(parsed),
            "state": self.get_state(),
        }

    def chat(self, message: str) -> Dict[str, Any]:
        now = datetime.now()
        s = self.settings_store.load()
        self.settings = s

        self._conversation_history.append({"role": "user", "content": message})
        if len(self._conversation_history) > 20:
            self._conversation_history = self._conversation_history[-20:]

        state = self.get_state()
        system_prompt = build_system_prompt(now=now, state=state, conversation_history=self._conversation_history[:-1])

        try:
            llm_reply, llm_actions = self._run_llm(system_prompt=system_prompt, user_message=message, settings=s)

            results: List[Dict[str, Any]] = []
            for a in llm_actions:
                results.append(self._execute_action(AssistantAction(tool=a["tool"], args=a["args"]), now=now))

            reply = llm_reply.strip() if isinstance(llm_reply, str) else ""
            if not reply and results:
                agenda_res = next((r for r in results if r.get("tool") == "get_agenda"), None)
                if agenda_res and "agenda" in agenda_res:
                    reply = "Here's what I found: " + self._format_agenda(agenda_res["agenda"])
                else:
                    reply = "Done! Is there anything else I can help you with?"
            if not reply and not results:
                reply = "I'm here to help! What would you like me to do?"

            self._conversation_history.append({"role": "assistant", "content": reply})
            return {"ok": True, "reply": reply, "intent": "llm", "results": results, "state": self.get_state()}
        except Exception as e:
            error_reply = f"I had trouble processing that. Please make sure you have an LLM provider configured in Settings (OpenAI or Gemma). Error: {str(e)[:100]}"
            self._conversation_history.append({"role": "assistant", "content": error_reply})
            return {"ok": False, "reply": error_reply, "intent": "error", "results": [], "state": self.get_state()}

    def _run_llm(self, system_prompt: str, user_message: str, settings: AppSettings):
        provider = (settings.provider or "openai").lower().strip()

        if provider == "gemma":
            if self._gemma_provider is None:
                self._gemma_provider = GemmaProvider(model_id=settings.gemma_model_id)
            res = self._gemma_provider.run(system_prompt=system_prompt, user_message=user_message)
            return res.reply, res.actions

        if self._openai_provider is None:
            self._openai_provider = OpenAiProvider(api_key=settings.openai_api_key, model=settings.openai_model)
        res = self._openai_provider.run(system_prompt=system_prompt, user_message=user_message)
        return res.reply, res.actions

    def transcribe_and_chat(self, audio_base64: str, filename: str) -> Dict[str, Any]:
        text = self.assistant.transcribe_audio(audio_base64=audio_base64, filename=filename)
        chat_res = self.chat(text)
        chat_res["transcript"] = text
        return chat_res

    def tts(self, text: str) -> Dict[str, Any]:
        wav_b64 = self.assistant.generate_speech_wav_base64(text)
        return {"ok": True, "audio_wav_base64": wav_b64}

    def _execute_action(self, action: AssistantAction, now: datetime) -> Dict[str, Any]:
        now_iso = now.isoformat()

        if action.tool == "add_event":
            event_id = self.db.add_event(
                title=action.args["title"],
                start_iso=action.args["start_iso"],
                end_iso=action.args["end_iso"],
                location=action.args.get("location"),
                notes=action.args.get("notes"),
                source="assistant",
                now_iso=now_iso,
            )
            return {"tool": "add_event", "event_id": event_id}

        if action.tool == "add_task":
            task_id = self.db.add_task(
                title=action.args["title"],
                due_iso=action.args.get("due_iso"),
                notes=action.args.get("notes"),
                now_iso=now_iso,
            )
            return {"tool": "add_task", "task_id": task_id}

        if action.tool == "update_task":
            self.db.update_task(
                task_id=action.args["task_id"],
                title=action.args.get("title"),
                due_iso=action.args.get("due_iso"),
                completed=action.args.get("completed"),
                notes=action.args.get("notes"),
                now_iso=now_iso,
            )
            return {"tool": "update_task", "task_id": action.args["task_id"]}

        if action.tool == "update_event":
            self.db.update_event(
                event_id=action.args["event_id"],
                title=action.args.get("title"),
                start_iso=action.args.get("start_iso"),
                end_iso=action.args.get("end_iso"),
                location=action.args.get("location"),
                notes=action.args.get("notes"),
                now_iso=now_iso,
            )
            return {"tool": "update_event", "event_id": action.args["event_id"]}

        if action.tool == "delete_task":
            self.db.delete_task(task_id=action.args["task_id"])
            return {"tool": "delete_task", "task_id": action.args["task_id"]}

        if action.tool == "delete_event":
            self.db.delete_event(event_id=action.args["event_id"])
            return {"tool": "delete_event", "event_id": action.args["event_id"]}

        if action.tool == "get_agenda":
            events = self.db.get_events_between(action.args["start_iso"], action.args["end_iso"])
            tasks = self.db.get_tasks_due_between(action.args["start_iso"], action.args["end_iso"])
            return {"tool": "get_agenda", "agenda": {"events": events, "tasks": tasks}}

        return {"tool": action.tool, "error": "Unknown tool"}

    def _format_agenda(self, agenda: Dict[str, Any]) -> str:
        events = agenda.get("events", [])
        tasks = agenda.get("tasks", [])

        lines: List[str] = []
        if events:
            lines.append("Events:")
            for e in events:
                lines.append(f"- {e['start_iso']} {e['title']} (id {e['id']})")
        else:
            lines.append("No events found.")

        if tasks:
            lines.append("Tasks due:")
            for t in tasks:
                lines.append(f"- {t['due_iso']} {t['title']} (id {t['id']})")
        else:
            lines.append("No tasks due today.")

        return "\n".join(lines)
