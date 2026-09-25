"""Fine-tune a small causal language model to write NOTAM readings, with MLX on the Mac's GPU.

Trains on data/training/train.jsonl (build_dataset.py) in the reading format (reading_format.py):
the model sees the prompt template and learns only the reading and its end token. The language-model
head runs only at the positions it's scored on — with a 152k-token vocabulary, logits for every
prompt position would dwarf the rest of the step. The checkpoint with the lowest validation loss is
saved as a Hugging Face–layout folder (safetensors, config, tokenizer) for conversion/.

    python -m training.train --out data/models/qwen3-0.6b-notam
"""

import argparse
import json
import random
import shutil
import time
from pathlib import Path

import mlx.core as mx
import mlx.optimizers as optim
import numpy as np
from huggingface_hub import snapshot_download
from mlx import nn
from mlx.utils import tree_flatten
from mlx_lm import load

from training import reading_format
from training.paths import DATASET_DIR
from training.template import END_OF_READING, prompt_text

CONFIG_FILES = ("config.json", "tokenizer.json", "tokenizer_config.json", "generation_config.json")


def examples(path: Path, tokenizer) -> list[tuple[list[int], int]]:
    """Each example's token IDs and where its reading starts."""
    encoded = []
    with path.open(encoding="utf-8") as lines:
        for row in map(json.loads, lines):
            prompt = tokenizer.encode(prompt_text(row["prompt"]), add_special_tokens=False)
            reading = reading_format.encode(json.loads(row["completion"]), row["prompt"])
            answer = tokenizer.encode(reading + END_OF_READING, add_special_tokens=False)
            encoded.append((prompt + answer, len(prompt)))
    return encoded


def batches(data, tokens_per_batch: int, shuffle: bool, rng: random.Random):
    """Padded batches of similar length, about ``tokens_per_batch`` tokens each, with scoring targets."""
    order = sorted(range(len(data)), key=lambda i: len(data[i][0]))
    groups, current = [], []
    for index in order:
        longest = max([len(data[i][0]) for i in current] + [len(data[index][0])])
        if current and longest * (len(current) + 1) > tokens_per_batch:
            groups.append(current)
            current = []
        current.append(index)
    if current:
        groups.append(current)
    if shuffle:
        rng.shuffle(groups)
    for group in groups:
        width = max(len(data[i][0]) for i in group)
        ids = np.zeros((len(group), width), dtype=np.int32)
        rows, columns, targets = [], [], []
        for row, i in enumerate(group):
            tokens, reading_start = data[i]
            ids[row, : len(tokens)] = tokens
            for position in range(reading_start, len(tokens)):
                rows.append(row)
                columns.append(position - 1)
                targets.append(tokens[position])
        yield mx.array(ids), mx.array(rows), mx.array(columns), mx.array(targets)


def loss_on(model, ids, rows, columns, targets):
    hidden = model.model(ids)[rows, columns]
    logits = model.model.embed_tokens.as_linear(hidden) if not hasattr(model, "lm_head") else model.lm_head(hidden)
    return nn.losses.cross_entropy(logits.astype(mx.float32), targets, reduction="mean")


def validation_loss(model, data, tokens_per_batch: int) -> float:
    losses = [loss_on(model, *batch).item() for batch in batches(data, tokens_per_batch, False, random.Random(0))]
    return sum(losses) / max(len(losses), 1)


def save(model, base: Path, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    mx.save_safetensors(str(out / "model.safetensors"), dict(tree_flatten(model.parameters())))
    for name in CONFIG_FILES:
        if (base / name).exists():
            shutil.copyfile(base / name, out / name)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="Qwen/Qwen3-0.6B")
    parser.add_argument("--data", type=Path, default=DATASET_DIR)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--tokens-per-batch", type=int, default=8192)
    parser.add_argument("--warmup-share", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=2027)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    mx.random.seed(args.seed)
    base = Path(snapshot_download(args.base)) if not Path(args.base).exists() else Path(args.base)
    model, tokenizer = load(str(base))
    train = examples(args.data / "train.jsonl", tokenizer)
    val = examples(args.data / "val.jsonl", tokenizer)
    steps_per_epoch = sum(1 for _ in batches(train, args.tokens_per_batch, False, rng))
    total = steps_per_epoch * args.epochs
    warmup = max(1, int(total * args.warmup_share))
    schedule = optim.join_schedules(
        [
            optim.linear_schedule(args.learning_rate / warmup, args.learning_rate, warmup),
            optim.cosine_decay(args.learning_rate, max(1, total - warmup)),
        ],
        [warmup],
    )
    optimizer = optim.AdamW(learning_rate=schedule, weight_decay=0.0)
    step_loss_and_grad = nn.value_and_grad(model, loss_on)
    print(f"{len(train)} train, {len(val)} validation examples; {total} steps")

    best = validation_loss(model, val, args.tokens_per_batch)
    print(f"epoch 0: validation loss {best:.4f}")
    step, started = 0, time.perf_counter()
    for epoch in range(1, args.epochs + 1):
        model.train()
        for batch in batches(train, args.tokens_per_batch, True, rng):
            loss, grads = step_loss_and_grad(model, *batch)
            grads, _ = optim.clip_grad_norm(grads, 1.0)
            optimizer.update(model, grads)
            mx.eval(model.parameters(), optimizer.state, loss)
            step += 1
            if step % 25 == 0:
                print(f"  step {step}/{total}: loss {loss.item():.4f} ({time.perf_counter() - started:.0f}s)")
        model.eval()
        current = validation_loss(model, val, args.tokens_per_batch)
        print(f"epoch {epoch}: validation loss {current:.4f} ({time.perf_counter() - started:.0f}s)")
        if current < best:
            best = current
            save(model, base, args.out)
            print(f"  saved to {args.out}")


if __name__ == "__main__":
    main()
