"""Local vision-language model - no cloud, no API key.

Preferred: Qwen2.5-VL-7B-Instruct (Apache-2.0), loaded 4-bit (NF4, ~5 GB) so it fits a 6 GB station GPU; layers that
do not fit spill to system RAM. Fallback: Qwen2-VL-2B-Instruct (fp16) if the 7B is not downloaded or fails to load.

It looks at the part and the defect crop itself, so answers and defect descriptions are grounded in
both the pixels and the inspection evidence. Runs on the station GPU; one request at a time.
"""
from __future__ import annotations

import json
import threading

import torch
from PIL import Image

BIG = "Qwen/Qwen2.5-VL-7B-Instruct"
SMALL = "Qwen/Qwen2-VL-2B-Instruct"


def _cached(repo: str) -> bool:
    try:
        from huggingface_hub import scan_cache_dir

        for r in scan_cache_dir().repos:
            if r.repo_id == repo:
                return any(f.file_name.endswith(".safetensors") for rev in r.revisions for f in rev.files) and \
                    sum(1 for rev in r.revisions for f in rev.files if f.file_name.endswith(".safetensors")) >= (5 if repo == BIG else 1)
    except Exception:
        pass
    return False


MODEL = BIG if _cached(BIG) else SMALL
_M = None
_LOCK = threading.Lock()
_LAST = [0.0]
IDLE_UNLOAD_S = 120


def _janitor():
    import time

    while True:
        time.sleep(30)
        global _M
        if _M is not None and time.time() - _LAST[0] > IDLE_UNLOAD_S:
            with _LOCK:
                if _M is not None and time.time() - _LAST[0] > IDLE_UNLOAD_S:
                    _M = None
                    import gc

                    gc.collect()
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()


threading.Thread(target=_janitor, daemon=True, name="vlm-janitor").start()
NL = chr(10)
LANG = {"en": "English", "hi": "Hindi", "te": "Telugu"}


def _fits_big() -> bool:
    """The 7B in 4-bit needs ~5.6 GiB of GPU memory to run entirely on the GPU. Spilling layers to the CPU keeps
    them unquantised (~14 GiB of RAM), so without that much free RAM a partial fit only crashes or thrashes."""
    if not torch.cuda.is_available():
        return False
    try:
        import psutil

        free_gpu = torch.cuda.mem_get_info()[0] / 2 ** 30
        free_ram = psutil.virtual_memory().available / 2 ** 30
        return free_gpu >= 5.6 or (free_gpu >= 3.0 and free_ram >= 14)
    except Exception:
        return False


def _load():
    global _M, MODEL
    if _M is None:
        if MODEL == SMALL and _cached(BIG):  # the 7B finished downloading while the station was running
            MODEL = BIG
        if MODEL == BIG and not _fits_big():
            print("[vlm] Qwen2.5-VL-7B does not fit next to the inspection models on this machine "
                  "(needs ~5.6 GiB free GPU memory, or ~14 GiB free RAM for offloaded layers); using Qwen2-VL-2B")
            MODEL = SMALL
        from transformers import AutoProcessor

        dev = "cuda" if torch.cuda.is_available() else "cpu"
        model = None
        if MODEL == BIG and dev == "cuda":
            try:
                from transformers import BitsAndBytesConfig, Qwen2_5_VLForConditionalGeneration

                q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.float16,
                                       bnb_4bit_use_double_quant=True, llm_int8_enable_fp32_cpu_offload=True)
                free = torch.cuda.mem_get_info()[0] / 2 ** 30
                model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                    BIG, quantization_config=q, torch_dtype=torch.float16, device_map="auto",
                    max_memory={0: f"{max(1.0, free - 0.9):.1f}GiB", "cpu": "24GiB"}).eval()
                dev = "cuda"
            except Exception as e:  # not enough memory / no bitsandbytes: fall back to the 2B
                print(f"[vlm] 7B failed to load ({type(e).__name__}: {e}); falling back to {SMALL}")
                model = None
                MODEL = SMALL
                import gc

                gc.collect()
                torch.cuda.empty_cache()
        if model is None:
            from transformers import Qwen2VLForConditionalGeneration

            model = Qwen2VLForConditionalGeneration.from_pretrained(
                SMALL, torch_dtype=torch.float16 if dev == "cuda" else torch.float32).to(dev).eval()
        # few image tokens: fast, and fits next to the vision models on a 6 GB GPU
        proc = AutoProcessor.from_pretrained(MODEL, min_pixels=128 * 28 * 28, max_pixels=320 * 28 * 28)
        _M = (model, proc, dev)
    return _M


def available() -> bool:
    try:
        from huggingface_hub import try_to_load_from_cache

        return try_to_load_from_cache(MODEL, "config.json") is not None or try_to_load_from_cache(SMALL, "config.json") is not None
    except Exception:
        return False


def generate(images: list[Image.Image], prompt: str, max_new_tokens: int = 160) -> str:
    import time

    with _LOCK:
        _LAST[0] = time.time()
        model, proc, dev = _load()
        content = [{"type": "image"} for _ in images] + [{"type": "text", "text": prompt}]
        msgs = [{"role": "user", "content": content}]
        text = proc.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        inputs = proc(text=[text], images=images or None, return_tensors="pt").to(dev)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
        ans = proc.batch_decode(out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0]
        _LAST[0] = time.time()
        return ans.strip()


def describe_region(part: Image.Image, crop: Image.Image, label: str) -> str:
    prompt = ("You are an industrial visual inspector. The first image is the whole part, the second is a close-up of a "
              f"region an anomaly detector flagged (an image classifier guessed: {label}). In one or two sentences, say "
              "what is visibly wrong in the close-up, roughly where it is on the part, and how serious it looks. If the "
              "close-up looks normal, say so plainly. Do not invent measurements.")
    return generate([part.convert("RGB").resize((448, 448)), crop.convert("RGB").resize((336, 336))], prompt, 120)


def answer(question: str, facts: str, part: Image.Image | None, lang: str = "en") -> str:
    prompt = ("You are Sandeha, the explanation layer of an industrial inspection station. The image is the inspected part. "
              "Answer the operator's question using ONLY these facts and what you can see in the image. After each claim, "
              "copy the tag of the fact you used, e.g. [region R1]. If the facts do not answer the question, say so. "
              "Decisions change only through two independent reviewers, never through chat. "
              f"Answer in 2-4 short sentences in {LANG.get(lang, 'English')}." + NL + NL + "Facts:" + NL + facts + NL + NL + f"Question: {question}")
    imgs = [part.convert("RGB").resize((448, 448))] if part is not None else []
    return generate(imgs, prompt, 200)
