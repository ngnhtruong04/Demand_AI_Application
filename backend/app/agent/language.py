"""app.agent.language — Language detector strictly constrained to English ('en') and Vietnamese ('vi')."""
from __future__ import annotations

import re

# Vietnamese specific diacritics
VI_DIACRITICS = re.compile(
    r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]",
    re.IGNORECASE,
)

VI_COMMON_WORDS = {
    "là", "của", "và", "cho", "sản", "phẩm", "hàng", "tồn", "kho", "dự", "báo",
    "bán", "giá", "nhu", "cầu", "bao", "nhiêu", "thế", "nào", "sao", "rồi",
    "đứt", "hết", "đặt", "thêm", "nguy", "cơ", "gì", "này", "mặt", "chi", "tiết",
    "phân", "tích", "đối", "thủ", "ngành", "so", "sánh", "yếu", "tố", "ảnh", "hưởng",
    "được", "không", "có", "trong", "ngày", "tuần", "tháng", "lấy", "xem", "kiểm", "tra"
}

EN_COMMON_WORDS = {
    "the", "is", "for", "item", "forecast", "stock", "what", "how", "why", "analyze",
    "sku", "show", "tell", "inventory", "status", "risk", "demand", "supply", "peers",
    "drivers", "category", "compare", "daily", "trend", "days", "reorder", "critical",
    "hello", "hi", "hey", "good", "morning", "afternoon", "who", "which"
}


def detect_language(text: str, default: str = "vi") -> str:
    """Detect if query is Vietnamese ('vi') or English ('en').
    
    Strictly constrained to only these two languages per specification.
    """
    if not text or not text.strip():
        return default

    clean = text.strip().lower()

    # 1. Definite match by Vietnamese diacritics
    if VI_DIACRITICS.search(clean):
        return "vi"

    # Neutral codes / pure SKU codes / bare slash commands defer to UI default
    if re.fullmatch(r"sku[-_\s]?\d+", clean) or re.fullmatch(r"/[a-z]+(\s+sku[-_\s]?\d+)?", clean):
        return default

    # 2. Match Vietnamese words
    tokens = set(re.findall(r"\b[a-z_à-ỹđ]+\b", clean))
    vi_count = len(tokens.intersection(VI_COMMON_WORDS))
    en_count = len(tokens.intersection(EN_COMMON_WORDS))

    if vi_count > en_count:
        return "vi"
    if en_count > vi_count:
        return "en"

    # 3. If English words present and no Vietnamese indicators
    if en_count > 0 and vi_count == 0:
        return "en"

    return default
