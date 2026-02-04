import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List


@dataclass
class LlmResult:
    reply: str
    actions: List[Dict[str, Any]]


def build_tools_schema() -> List[Dict[str, Any]]:
    return [
        {
            "name": "add_task",
            "args": {"title": "string", "due_iso": "string|null", "notes": "string|null"},
        },
        {
            "name": "update_task",
            "args": {"task_id": "int", "title": "string|null", "due_iso": "string|null", "completed": "bool|null", "notes": "string|null"},
        },
        {"name": "delete_task", "args": {"task_id": "int"}},
        {
            "name": "add_event",
            "args": {"title": "string", "start_iso": "string", "end_iso": "string", "location": "string|null", "notes": "string|null"},
        },
        {
            "name": "update_event",
            "args": {"event_id": "int", "title": "string|null", "start_iso": "string|null", "end_iso": "string|null", "location": "string|null", "notes": "string|null"},
        },
        {"name": "delete_event", "args": {"event_id": "int"}},
        {"name": "get_agenda", "args": {"start_iso": "string", "end_iso": "string"}},
    ]


def build_system_prompt(now: datetime, state: Dict[str, Any], conversation_history: List[Dict[str, str]] = None) -> str:
    tools = build_tools_schema()
    tasks = state.get("tasks") or []
    events = state.get("events") or []

    tasks_preview = [
        {"id": t.get("id"), "title": t.get("title"), "due_iso": t.get("due_iso"), "completed": t.get("completed")}
        for t in tasks[:50]
    ]
    events_preview = [
        {"id": e.get("id"), "title": e.get("title"), "start_iso": e.get("start_iso"), "end_iso": e.get("end_iso")}
        for e in events[:50]
    ]

    history_text = ""
    if conversation_history:
        history_text = "Recent conversation:\n" + "\n".join(
            [f"{m['role'].upper()}: {m['content']}" for m in conversation_history[-10:]]
        ) + "\n\n"

    return (
        "You are Felix, a friendly and helpful AI secretary assistant. "
        "You help manage tasks and calendar events through natural conversation. "
        "IMPORTANT BEHAVIORS:\n"
        "1. Be conversational and friendly - greet users, use their name if known\n"
        "2. ASK CLARIFYING QUESTIONS when information is missing (e.g., 'What time should I schedule that meeting?', 'When is this task due?')\n"
        "3. Confirm actions before executing them (e.g., 'I'll add a meeting with Bob tomorrow at 3pm for 30 minutes. Sound good?')\n"
        "4. Proactively offer help (e.g., 'Would you like me to check your schedule for conflicts?')\n"
        "5. Keep responses concise but warm - you'll be speaking these aloud\n"
        "6. If the user just says hi or wants to chat, engage naturally without requiring actions\n\n"
        "Return a single JSON object with keys: reply (string), actions (array). "
        "The reply should be natural speech - it will be spoken aloud via TTS. "
        "Each action is an object with keys: tool (string), args (object). "
        "Only use tool names from the provided tool list. "
        "If no tools are needed or you need more info, return actions as an empty array. "
        "Use ISO 8601 datetimes for due_iso/start_iso/end_iso. "
        "Output JSON only. "
        f"Current local datetime is: {now.isoformat()}. "
        f"{history_text}"
        f"Tools: {json.dumps(tools)} "
        f"Current tasks: {json.dumps(tasks_preview)} "
        f"Current events: {json.dumps(events_preview)}"
    )


class BaseProvider:
    def run(self, system_prompt: str, user_message: str) -> LlmResult:
        raise NotImplementedError()


class OpenAiProvider(BaseProvider):
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def run(self, system_prompt: str, user_message: str) -> LlmResult:
        try:
            from openai import OpenAI
        except Exception as e:
            raise RuntimeError("openai package is not installed") from e

        key = (self.api_key or "").strip()
        if not key:
            raise RuntimeError("OpenAI API key is missing")

        client = OpenAI(api_key=key)
        resp = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
        )

        content = resp.choices[0].message.content or "{}"
        return _parse_llm_json(content)


class GemmaProvider(BaseProvider):
    def __init__(self, model_id: str):
        self.model_id = model_id
        self._processor = None
        self._model = None

    def _load(self):
        if self._model is not None and self._processor is not None:
            return

        import torch
        
        if not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA is not available! PyTorch is using CPU which is very slow. "
                "Install PyTorch with CUDA: pip install torch --index-url https://download.pytorch.org/whl/cu124"
            )
        
        print(f"[Felix] Loading Gemma on GPU: {torch.cuda.get_device_name(0)}")

        try:
            from transformers import AutoProcessor, Gemma3ForConditionalGeneration
            
            self._processor = AutoProcessor.from_pretrained(self.model_id)
            self._model = Gemma3ForConditionalGeneration.from_pretrained(
                self.model_id,
                device_map="cuda",
                torch_dtype=torch.bfloat16,
                attn_implementation="flash_attention_2" if self._has_flash_attn() else "sdpa",
            )
            self._model.eval()
            self._is_gemma3 = True
            print(f"[Felix] Gemma 3 loaded successfully on CUDA with {'flash_attention_2' if self._has_flash_attn() else 'sdpa'}")
        except ImportError:
            from transformers import AutoTokenizer, AutoModelForCausalLM
            self._processor = AutoTokenizer.from_pretrained(self.model_id)
            self._model = AutoModelForCausalLM.from_pretrained(
                self.model_id,
                device_map="cuda",
                torch_dtype=torch.bfloat16,
            )
            self._model.eval()
            self._is_gemma3 = False
            print("[Felix] Gemma loaded with legacy API on CUDA")
        except Exception as e:
            from transformers import AutoTokenizer, AutoModelForCausalLM
            print(f"[Felix] Gemma3ForConditionalGeneration failed: {e}, trying legacy...")
            self._processor = AutoTokenizer.from_pretrained(self.model_id)
            self._model = AutoModelForCausalLM.from_pretrained(
                self.model_id,
                device_map="cuda",
                torch_dtype=torch.bfloat16,
            )
            self._model.eval()
            self._is_gemma3 = False
            print("[Felix] Gemma loaded with legacy API on CUDA")

    def _has_flash_attn(self) -> bool:
        try:
            import flash_attn
            return True
        except ImportError:
            return False

    def run(self, system_prompt: str, user_message: str) -> LlmResult:
        self._load()
        import torch

        processor = self._processor
        model = self._model

        if getattr(self, '_is_gemma3', False):
            messages = [
                {
                    "role": "system",
                    "content": [{"type": "text", "text": system_prompt}]
                },
                {
                    "role": "user",
                    "content": [{"type": "text", "text": user_message}]
                }
            ]

            inputs = processor.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=True,
                return_dict=True,
                return_tensors="pt"
            ).to(model.device, dtype=torch.bfloat16)

            input_len = inputs["input_ids"].shape[-1]

            with torch.inference_mode():
                out = model.generate(
                    **inputs,
                    max_new_tokens=1024,
                    do_sample=False,
                )

            generation = out[0][input_len:]
            text = processor.decode(generation, skip_special_tokens=True)
        else:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]

            if hasattr(processor, "apply_chat_template"):
                prompt = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                inputs = processor(prompt, return_tensors="pt").to(model.device)
            else:
                prompt = system_prompt + "\n\nUser: " + user_message + "\nAssistant:"
                inputs = processor(prompt, return_tensors="pt").to(model.device)

            with torch.inference_mode():
                out = model.generate(
                    **inputs,
                    max_new_tokens=1024,
                    do_sample=False,
                    eos_token_id=processor.eos_token_id,
                )

            text = processor.decode(out[0], skip_special_tokens=True)

        json_text = _extract_json_object(text)
        return _parse_llm_json(json_text)


def _extract_json_object(text: str) -> str:
    s = text.strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return "{}"
    return s[start : end + 1]


def _parse_llm_json(content: str) -> LlmResult:
    try:
        obj = json.loads(content)
    except Exception:
        obj = {}

    reply = obj.get("reply") if isinstance(obj, dict) else None
    actions = obj.get("actions") if isinstance(obj, dict) else None

    if not isinstance(reply, str):
        reply = ""
    if not isinstance(actions, list):
        actions = []

    clean_actions: List[Dict[str, Any]] = []
    for a in actions:
        if not isinstance(a, dict):
            continue
        tool = a.get("tool")
        args = a.get("args")
        if not isinstance(tool, str) or not isinstance(args, dict):
            continue
        clean_actions.append({"tool": tool, "args": args})

    return LlmResult(reply=reply, actions=clean_actions)
