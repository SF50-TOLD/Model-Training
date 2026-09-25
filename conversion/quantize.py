"""Weight-only quantization of Qwen3Static via coreai::constexpr_blockwise_shift_scale.

Every nn.Linear (and the tied embedding / LM head) keeps symmetric integer weights
plus fp16 scales; the Core AI compiler sees a constexpr dequantize feeding the matmul.
int8 uses one scale per output channel; int4 uses one scale per 32-input block.
"""

import coreai_torch._compression.custom_layers  # noqa: F401  (registers torch.ops.coreai.*)
import torch
import torch.nn.functional as F  # noqa: N812 (the PyTorch idiom)
from torch import nn

BLOCK = {"int8": None, "int4": 32, "int8b32": 32, "int4b16": 16}
BITS = {"int8": 8, "int4": 4, "int8b32": 8, "int4b16": 4}
LOGICAL_DTYPE = {"int8": torch.int8, "int4": torch.int4, "int8b32": torch.int8, "int4b16": torch.int4}


def quantize_weight(weight: torch.Tensor, scheme: str) -> tuple[torch.Tensor, torch.Tensor]:
    out_features, in_features = weight.shape
    block = BLOCK[scheme] or in_features
    qmax = 2 ** (BITS[scheme] - 1) - 1
    blocks = weight.float().reshape(out_features, in_features // block, block)
    scale = blocks.abs().amax(-1, keepdim=True).clamp(min=1e-8) / qmax
    quantized = (blocks / scale).round().clamp(-qmax - 1, qmax).to(torch.int8)
    return quantized.reshape(out_features, in_features), scale.squeeze(-1).to(weight.dtype)


class QuantizedWeight(nn.Module):
    def __init__(self, weight: torch.Tensor, scheme: str) -> None:
        super().__init__()
        quantized, scale = quantize_weight(weight, scheme)
        self.register_buffer("quantized_data", quantized)
        self.register_buffer("scale", scale)
        self.input_dtype = LOGICAL_DTYPE[scheme]

    def forward(self) -> torch.Tensor:
        return torch.ops.coreai.constexpr_blockwise_shift_scale(
            self.quantized_data, self.scale, input_dtype=self.input_dtype
        )


class QuantizedLinear(nn.Module):
    def __init__(self, linear: nn.Linear, scheme: str) -> None:
        super().__init__()
        self.weight = QuantizedWeight(linear.weight.data, scheme)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.linear(x, self.weight())


class QuantizedEmbedding(nn.Module):
    """Tied embedding: gathers rows for input tokens and serves as the LM head."""

    def __init__(self, embedding: nn.Embedding, scheme: str) -> None:
        super().__init__()
        self.quantized = QuantizedWeight(embedding.weight.data, scheme)

    @property
    def weight(self) -> torch.Tensor:
        return self.quantized()

    def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
        return F.embedding(input_ids, self.weight)


def quantize_linears(model: nn.Module, scheme: str) -> None:
    for module in list(model.modules()):
        for name, child in list(module.named_children()):
            if isinstance(child, nn.Linear):
                setattr(module, name, QuantizedLinear(child, scheme))
    model.embed_tokens = QuantizedEmbedding(model.embed_tokens, scheme)
