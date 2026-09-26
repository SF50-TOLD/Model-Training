"""Convert a fine-tuned NOTAM model to the folder the app's `NOTAMModelReader` loads.

The folder holds the Core AI model (`model.aimodel`), the tokenizer files, and `notam-model.json`,
which tells the reader the prompt template, end token, vocabulary and context sizes, the schema
version the model was trained on, the model's version, and the fields it may propose
(conversion/proposable.py; none unless listed).

    python -m conversion.convert data/models/qwen3-0.6b-notam data/models/qwen3-0.6b-notam-coreai --quantize int8b32 \
        --proposable-fields closedLength,closedEnd,rwyCC,contaminants
"""

import argparse
import json
import shutil
import time
from pathlib import Path

import coreai_torch
import torch
from coreai_torch import TorchConverter
from torch.export import Dim
from transformers import AutoTokenizer

from conversion.proposable import proposable_fields
from conversion.quantize import quantize_linears
from conversion.qwen3_static import Qwen3Static
from notam_gold.schema import schema_version
from training.template import END_OF_READING, PROMPT_TEMPLATE

MODEL_FILE = "model.aimodel"
MANIFEST_FILE = "notam-model.json"
TOKENIZER_FILES = ("tokenizer.json", "tokenizer_config.json", "config.json")
MAXIMUM_OUTPUT_TOKENS = 160


def export(model: Qwen3Static) -> torch.export.ExportedProgram:
    tokens = Dim("tokens", min=1, max=model.max_context)
    sample_ids = torch.zeros((1, 8), dtype=torch.int32)
    sample_positions = torch.arange(8, dtype=torch.int32)
    with torch.no_grad():
        program = torch.export.export(
            model,
            args=(sample_ids, sample_positions),
            dynamic_shapes={"input_ids": {1: tokens}, "positions": {0: tokens}},
        )
    return program.run_decompositions(coreai_torch.get_decomp_table())


def convert(model: Qwen3Static, destination: Path):
    program = (
        TorchConverter()
        .add_exported_program(
            export(model),
            input_names=["input_ids", "positions"],
            output_names=["logits"],
            state_names=["k_cache", "v_cache"],
        )
        .to_coreai()
    )
    program.save_asset(destination)


def manifest(tokenizer, model: Qwen3Static, version: str, proposable: list[str]) -> dict:
    return {
        "model": MODEL_FILE,
        "modelVersion": version,
        "schemaVersion": schema_version(),
        "promptTemplate": PROMPT_TEMPLATE,
        "endOfSequence": tokenizer.convert_tokens_to_ids(END_OF_READING),
        "vocabularySize": model.cfg["vocab_size"],
        "contextLength": model.max_context,
        "maximumOutputTokens": MAXIMUM_OUTPUT_TOKENS,
        "proposableFields": proposable,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("trained", type=Path, help="Hugging Face model folder from training/train.py")
    parser.add_argument("out", type=Path, help="model folder to write")
    parser.add_argument("--quantize", default="none", choices=["none", "int8", "int4", "int8b32", "int4b16"])
    parser.add_argument("--max-context", type=int, default=1536)
    parser.add_argument("--version", help="the model's version (default: the output folder's name)")
    parser.add_argument(
        "--proposable-fields", type=proposable_fields, default=[], help="fields that cleared the gate, comma-separated"
    )
    args = parser.parse_args()

    model = Qwen3Static.from_pretrained(args.trained, args.max_context, torch.float16)
    if args.quantize != "none":
        quantize_linears(model, args.quantize)
    tokenizer = AutoTokenizer.from_pretrained(args.trained)

    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True)
    started = time.perf_counter()
    convert(model, args.out / MODEL_FILE)
    for name in TOKENIZER_FILES:
        shutil.copy(args.trained / name, args.out / name)
    contents = manifest(tokenizer, model, args.version or args.out.name, args.proposable_fields)
    (args.out / MANIFEST_FILE).write_text(json.dumps(contents, indent=2) + "\n")
    print(f"converted in {time.perf_counter() - started:.0f}s -> {args.out}")


if __name__ == "__main__":
    main()
