"""Định tuyến theo dải bất định — hạt nhân của cost model."""

ACCEPT_P = 0.70
REJECT_P = 0.35
EXPECTED_UNCERTAIN_SHARE = 0.08


def decision_from_stage2(probs: dict[str, float]) -> str:
    """accept | reject | uncertain"""
    from pipeline.stage2_classifier import route

    return route(probs, ACCEPT_P, REJECT_P)


def needs_vlm(decision: str) -> bool:
    return decision == "uncertain"


def fallback_decision(decision: str, vlm_enabled: bool) -> str:
    """Khi Stage 3 tắt: uncertain -> human_review_queue thay vì gọi API."""
    if decision == "uncertain" and not vlm_enabled:
        return "human_review"
    return decision


def cost_per_1m_images(stage3_share: float = EXPECTED_UNCERTAIN_SHARE) -> dict:
    """TODO(impl): cắm đơn giá thật đo được từ GEMINI API khi có key."""
    return {
        "stage1_cpu_usd": 0.30,
        "stage2_gpu_usd": 0.15,
        "stage3_share": stage3_share,
        "stage3_vlm_usd_range": (0.08, 0.31),
        "total_usd_range": (0.53 + stage3_share * 0.08, 0.45 + stage3_share * 0.31),
        "note": "Đơn giá token Gemini phải lấy từ trang giá chính thức tại thời điểm build.",
    }


def vlm_cost_per_image(
    input_usd_per_1m: float, output_usd_per_1m: float, in_tokens: int = 1320, out_tokens: int = 60
) -> float:
    return in_tokens / 1e6 * input_usd_per_1m + out_tokens / 1e6 * output_usd_per_1m
