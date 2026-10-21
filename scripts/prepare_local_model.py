"""Download only the official tokenizer/config and safetensors/ONNX files needed locally."""

from __future__ import annotations

import json
import urllib.request

from retrieval.embed import EMBED_MODEL
from storage.runtime import data_dir


def main():
    repo = data_dir() / "models" / ("models--" + EMBED_MODEL.replace("/", "--"))
    with urllib.request.urlopen(
        "https://huggingface.co/api/models/" + EMBED_MODEL, timeout=30
    ) as response:
        info = json.load(response)
    revision = info["sha"]
    root = repo / "snapshots" / revision
    files = [
        "config.json",
        "config_sentence_transformers.json",
        "modules.json",
        "sentence_bert_config.json",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "1_Pooling/config.json",
        "model.safetensors",
        "onnx/model_quint8_avx2.onnx",
    ]
    for name in files:
        target = root / name
        if target.exists() and target.stat().st_size:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        print("[model] downloading", name, flush=True)
        temporary = target.with_suffix(target.suffix + ".download")
        url = f"https://huggingface.co/{EMBED_MODEL}/resolve/{revision}/{name}"
        with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as stream:
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
        temporary.replace(target)
    (repo / "refs").mkdir(parents=True, exist_ok=True)
    (repo / "refs" / "main").write_text(revision, encoding="utf-8")
    print("[model] ready:", revision)


if __name__ == "__main__":
    main()
