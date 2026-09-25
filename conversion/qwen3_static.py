"""Export-friendly Qwen3 decoder with a static, caller-owned KV cache.

The KV cache lives in two mutable buffers (``k_cache`` and ``v_cache``) laid out
as ``[layers * max_context, kv_heads, head_dim]`` so each step's update is a
single ``index_put`` on rows ``layer * max_context + position``. One forward
handles both prefill (T tokens) and decode (T = 1): it writes the new keys and
values at ``positions`` and attends over the whole cache under a mask that hides
every slot past each query's own position.
"""

import json
from pathlib import Path

import torch
import torch.nn.functional as F  # noqa: N812 (the PyTorch idiom)
from safetensors.torch import load_file
from torch import nn


def rope_theta(cfg: dict) -> float:
    """The RoPE base; Transformers 5 moved it under rope_parameters."""
    return cfg.get("rope_theta") or cfg["rope_parameters"]["rope_theta"]


class RMSNorm(nn.Module):
    def __init__(self, dim: int, eps: float) -> None:
        super().__init__()
        self.weight = nn.Parameter(torch.ones(dim))
        self.eps = eps

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        dtype = x.dtype
        x = x.float()
        x = x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps)
        return self.weight * x.to(dtype)


def rotate_half(x: torch.Tensor) -> torch.Tensor:
    half = x.shape[-1] // 2
    return torch.cat((-x[..., half:], x[..., :half]), dim=-1)


class Attention(nn.Module):
    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self.heads = cfg["num_attention_heads"]
        self.kv_heads = cfg["num_key_value_heads"]
        self.head_dim = cfg["head_dim"]
        hidden = cfg["hidden_size"]
        self.q_proj = nn.Linear(hidden, self.heads * self.head_dim, bias=False)
        self.k_proj = nn.Linear(hidden, self.kv_heads * self.head_dim, bias=False)
        self.v_proj = nn.Linear(hidden, self.kv_heads * self.head_dim, bias=False)
        self.o_proj = nn.Linear(self.heads * self.head_dim, hidden, bias=False)
        self.q_norm = RMSNorm(self.head_dim, cfg["rms_norm_eps"])
        self.k_norm = RMSNorm(self.head_dim, cfg["rms_norm_eps"])


class MLP(nn.Module):
    def __init__(self, cfg: dict) -> None:
        super().__init__()
        hidden, inter = cfg["hidden_size"], cfg["intermediate_size"]
        self.gate_proj = nn.Linear(hidden, inter, bias=False)
        self.up_proj = nn.Linear(hidden, inter, bias=False)
        self.down_proj = nn.Linear(inter, hidden, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.down_proj(F.silu(self.gate_proj(x)) * self.up_proj(x))


class Layer(nn.Module):
    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self.self_attn = Attention(cfg)
        self.mlp = MLP(cfg)
        self.input_layernorm = RMSNorm(cfg["hidden_size"], cfg["rms_norm_eps"])
        self.post_attention_layernorm = RMSNorm(cfg["hidden_size"], cfg["rms_norm_eps"])


class Qwen3Static(nn.Module):
    def __init__(self, cfg: dict, max_context: int, dtype: torch.dtype) -> None:
        super().__init__()
        self.cfg = cfg
        self.max_context = max_context
        self.layers_count = cfg["num_hidden_layers"]
        self.kv_heads = cfg["num_key_value_heads"]
        self.head_dim = cfg["head_dim"]
        self.embed_tokens = nn.Embedding(cfg["vocab_size"], cfg["hidden_size"])
        self.layers = nn.ModuleList(Layer(cfg) for _ in range(self.layers_count))
        self.norm = RMSNorm(cfg["hidden_size"], cfg["rms_norm_eps"])

        inv_freq = 1.0 / (rope_theta(cfg) ** (torch.arange(0, self.head_dim, 2, dtype=torch.float64) / self.head_dim))
        freqs = torch.outer(torch.arange(max_context, dtype=torch.float64), inv_freq)
        emb = torch.cat((freqs, freqs), dim=-1)
        self.register_buffer("rope_cos", emb.cos().to(dtype), persistent=False)
        self.register_buffer("rope_sin", emb.sin().to(dtype), persistent=False)

        cache_shape = (self.layers_count * max_context, self.kv_heads, self.head_dim)
        self.register_buffer("k_cache", torch.zeros(cache_shape, dtype=dtype))
        self.register_buffer("v_cache", torch.zeros(cache_shape, dtype=dtype))

    @classmethod
    def from_pretrained(cls, path: Path, max_context: int, dtype: torch.dtype) -> Qwen3Static:
        cfg = json.loads((path / "config.json").read_text())
        model = cls(cfg, max_context, dtype)
        state = {k.removeprefix("model."): v for k, v in load_file(path / "model.safetensors").items()}
        state.pop("lm_head.weight", None)
        missing, unexpected = model.load_state_dict(state, strict=False)
        assert not unexpected, unexpected
        assert set(missing) <= {"rope_cos", "rope_sin", "k_cache", "v_cache"}, missing
        return model.to(dtype).eval()

    def reset_cache(self) -> None:
        self.k_cache.zero_()
        self.v_cache.zero_()

    def forward(self, input_ids: torch.Tensor, positions: torch.Tensor) -> torch.Tensor:
        """Return last-token logits ``[1, vocab]`` for ``input_ids [1, T]`` at ``positions [T]``."""
        tokens = input_ids.shape[1]
        x = self.embed_tokens(input_ids)
        cos = self.rope_cos.index_select(0, positions)[None, None]
        sin = self.rope_sin.index_select(0, positions)[None, None]
        slots = torch.arange(self.max_context, dtype=positions.dtype)
        visible = slots[None, :] <= positions[:, None]
        mask = torch.zeros(visible.shape, dtype=x.dtype).masked_fill(~visible, torch.finfo(x.dtype).min)[None, None]

        for index, layer in enumerate(self.layers):
            x = x + self._attend(layer.self_attn, layer.input_layernorm(x), index, positions, cos, sin, mask, tokens)
            x = x + layer.mlp(layer.post_attention_layernorm(x))

        last = self.norm(x[:, -1])
        return F.linear(last, self.embed_tokens.weight)

    def _attend(self, attn, x, index, positions, cos, sin, mask, tokens):
        q = attn.q_norm(attn.q_proj(x).view(1, tokens, attn.heads, self.head_dim)).transpose(1, 2)
        k = attn.k_norm(attn.k_proj(x).view(1, tokens, self.kv_heads, self.head_dim)).transpose(1, 2)
        v = attn.v_proj(x).view(1, tokens, self.kv_heads, self.head_dim)
        q = q * cos + rotate_half(q) * sin
        k = k * cos + rotate_half(k) * sin

        rows = positions + index * self.max_context
        self.k_cache.index_put_((rows,), k[0].transpose(0, 1))
        self.v_cache.index_put_((rows,), v[0])

        start = index * self.max_context
        keys = self.k_cache[start : start + self.max_context].permute(1, 0, 2)[None]
        values = self.v_cache[start : start + self.max_context].permute(1, 0, 2)[None]
        out = F.scaled_dot_product_attention(q, keys, values, attn_mask=mask, enable_gqa=True)
        return attn.o_proj(out.transpose(1, 2).reshape(1, tokens, attn.heads * self.head_dim))
