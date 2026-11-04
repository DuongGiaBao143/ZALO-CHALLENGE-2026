"""Turing SDPA compatibility without changing Qwen's attention masks or scale."""
import logging


def configure_t4_sdpa():
    import torch
    if not torch.cuda.is_available() or torch.cuda.get_device_capability() != (7, 5):
        return
    from transformers.integrations import sdpa_attention
    if not hasattr(sdpa_attention, "use_gqa_in_sdpa"):
        raise RuntimeError("Unsupported Transformers SDPA integration; use requirements-kaggle-sft.txt")
    # shortcut: private HF hook for the pinned release; recheck when upgrading Transformers.
    # HF already repeats K/V and preserves masks when this predicate returns False.
    sdpa_attention.use_gqa_in_sdpa = lambda *args, **kwargs: False
    torch.backends.cuda.enable_flash_sdp(False)
    torch.backends.cuda.enable_math_sdp(False)
    torch.backends.cuda.enable_mem_efficient_sdp(True)
    logging.getLogger(__name__).info(
        "T4 SDPA: explicit KV expansion, memory-efficient kernel only; math fallback disabled"
    )
