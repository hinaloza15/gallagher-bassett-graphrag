"""LLM client for GraphRAG query planning.

Primary planner: Qwen3 14B served by Ollama.
Fallback planner: the project's existing local Transformers Qwen model.

The planner is used ONLY to map a question to the existing graph schema. It
never writes Cypher and never answers the user's claim question.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Dict, List

DEFAULT_OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_OLLAMA_MODEL = "qwen3:14b"


def _extract_json_object(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.replace("```json", "", 1).replace("```", "", 1).strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return {}


def _ollama_chat(system: str, user: str) -> dict:
    url = os.getenv("GRAPHRAG_OLLAMA_URL", DEFAULT_OLLAMA_URL)
    model = os.getenv("GRAPHRAG_PLANNER_MODEL", DEFAULT_OLLAMA_MODEL)
    timeout = float(os.getenv("GRAPHRAG_PLANNER_TIMEOUT", "120"))

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "think": False,
        "format": "json",
        "options": {
            "temperature": 0,
            "top_p": 0.1,
            "num_predict": 320,
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    message = data.get("message") or {}
    content = (message.get("content") or "").strip()
    parsed = _extract_json_object(content)
    if not parsed:
        thinking = (message.get("thinking") or "").strip()
        raise RuntimeError(
            "Ollama planner returned no valid JSON. "
            f"content={content[:180]!r}; thinking={thinking[:180]!r}"
        )
    return parsed


def _transformers_chat(system: str, user: str) -> dict:
    """Fallback to the Qwen already used by src.generation.answer_generator."""
    from src.generation.answer_generator import load_generator
    import torch

    tokenizer, model, device = load_generator()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        output = model.generate(
            **inputs,
            max_new_tokens=220,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )
    generated = output[0][inputs["input_ids"].shape[1]:]
    content = tokenizer.decode(generated, skip_special_tokens=True)
    parsed = _extract_json_object(content)
    if not parsed:
        raise RuntimeError(f"Fallback planner returned no valid JSON: {content[:300]}")
    return parsed


def run_planner(system: str, user: str) -> tuple[dict, str]:
    """Run configured planner and return (parsed_json, planner_name).

    GRAPHRAG_PLANNER_BACKEND values:
      - ollama (default): Qwen3 14B through local Ollama
      - transformers: existing local Qwen model
      - auto: try Ollama, then Transformers
    """
    backend = os.getenv("GRAPHRAG_PLANNER_BACKEND", "auto").strip().lower()

    if backend not in {"ollama", "transformers", "auto"}:
        raise ValueError("GRAPHRAG_PLANNER_BACKEND must be ollama, transformers, or auto")

    if backend in {"ollama", "auto"}:
        try:
            data = _ollama_chat(system, user)
            model = os.getenv("GRAPHRAG_PLANNER_MODEL", DEFAULT_OLLAMA_MODEL)
            return data, f"ollama:{model}"
        except Exception as exc:
            if backend == "ollama":
                raise
            print(f"[GraphRAG] Ollama planner unavailable; falling back: {exc}")

    data = _transformers_chat(system, user)
    return data, "transformers:fallback_qwen"
