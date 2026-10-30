from functools import lru_cache
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from src.config import GENERATION_MODEL

def get_device():
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"

@lru_cache(maxsize=1)
def load_generator():
    device = get_device()
    print(f"Loading {GENERATION_MODEL} on {device}")
    tokenizer = AutoTokenizer.from_pretrained(GENERATION_MODEL)

    if device == "cuda":
        model = AutoModelForCausalLM.from_pretrained(
            GENERATION_MODEL,
            torch_dtype=torch.float16,
            device_map="auto",
        )
    else:
        dtype = torch.float16 if device == "mps" else torch.float32
        model = AutoModelForCausalLM.from_pretrained(
            GENERATION_MODEL,
            torch_dtype=dtype,
        )
        model.to(device)

    model.eval()
    return tokenizer, model, device

def build_evidence(retrieved):
    blocks = []
    for i, row in enumerate(retrieved, start=1):
        blocks.append(
            f"[E{i}]\n"
            f"Claim: {row['claim_id']}\n"
            f"Note: {row['note_id']}\n"
            f"Chunk: {row['chunk_id']}\n"
            f"Text: {row['text']}"
        )
    return "\n\n".join(blocks)

def generate_answer(question: str, claim_id: str, retrieved, max_new_tokens=350):
    tokenizer, model, device = load_generator()
    evidence = build_evidence(retrieved)

    messages = [
        {
            "role": "system",
            "content": (
                "Answer workers' compensation claim questions using only the provided evidence. "
                "Do not invent facts. Cite factual statements using [E1], [E2], etc. "
                "If evidence conflicts, explicitly describe the conflict and cite both sides. "
                "If evidence is insufficient, say so."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Claim ID: {claim_id}\n\n"
                f"Question: {question}\n\n"
                f"Evidence:\n{evidence}\n\n"
                "Answer:"
            ),
        },
    ]

    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        output = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )

    generated = output[0][inputs["input_ids"].shape[1]:]
    return tokenizer.decode(generated, skip_special_tokens=True).strip()
