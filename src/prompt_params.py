"""로컬 LLM용 프롬프트 파라미터 계산기.

경량 모델이 동적 비례 배분 규칙을 스스로 해석하지 못하므로,
트랜스크립트 길이를 보고 파이썬에서 미리 계산해 프롬프트에 주입한다.

기존 compact.md 등 Claude/Gemini용 템플릿에는 영향 없음.
"""

def compute_params(char_count: int) -> dict:
    """트랜스크립트 문자 수 → 분량 파라미터 매핑.

    구간 기준은 templates/compact.md 의 동적 비례 배분 규칙과 동일.
    """
    if char_count <= 3_500:
        return {
            "overview_lines": 3,
            "argument_count": 2,
            "sentences_per_argument": 3,
            "keyword_count": 3,
        }
    if char_count <= 10_500:
        return {
            "overview_lines": 4,
            "argument_count": 3,
            "sentences_per_argument": 4,
            "keyword_count": 4,
        }
    if char_count <= 17_500:
        return {
            "overview_lines": 6,
            "argument_count": 3,
            "sentences_per_argument": 5,
            "keyword_count": 5,
        }
    if char_count <= 25_000:
        return {
            "overview_lines": 7,
            "argument_count": 4,
            "sentences_per_argument": 6,
            "keyword_count": 6,
        }
    return {
        "overview_lines": 9,
        "argument_count": 5,
        "sentences_per_argument": 7,
        "keyword_count": 7,
    }
