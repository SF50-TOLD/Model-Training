import mlx.core as mx
from mlx.utils import tree_flatten
from mlx_lm.models.qwen3 import Model, ModelArgs

from training.train import add_adapters, fused_weights


def tiny_qwen3() -> Model:
    return Model(
        ModelArgs(
            model_type="qwen3",
            hidden_size=32,
            num_hidden_layers=2,
            intermediate_size=64,
            num_attention_heads=4,
            num_key_value_heads=2,
            head_dim=8,
            rms_norm_eps=1e-6,
            vocab_size=50,
            max_position_embeddings=64,
            rope_theta=10000,
            tie_word_embeddings=True,
        )
    )


def test_fused_adapters_keep_the_base_layout_and_output():
    model = tiny_qwen3()
    base_names = set(dict(tree_flatten(model.parameters())))
    add_adapters(model, rank=4, scale=2.0)
    adapters = model.trainable_parameters()
    for adapter in adapters["model"]["layers"][0]["mlp"].values():
        adapter["lora_b"] = mx.random.normal(adapter["lora_b"].shape)
    model.update(adapters)
    ids = mx.array([[1, 2, 3, 4]])
    adapted = model(ids)

    weights = fused_weights(model)
    fused = tiny_qwen3()
    fused.load_weights(list(weights.items()))

    assert set(weights) == base_names
    assert mx.allclose(fused(ids), adapted, atol=1e-4)
