import logging
import os
import time

logger = logging.getLogger(__name__)

GEMINI_MODELS = {
    'pro':      'gemini-2.5-pro',
    'thinking': 'gemini-2.5-flash',
    'flash':    'gemini-2.0-flash',
}
FALLBACK_CHAIN = ['pro', 'thinking', 'flash']

FREE_TIER_LIMITS = {
    'pro':      '일 25회',
    'thinking': '일 500회',
    'flash':    '일 1,500회',
}


def build_prompt(template_path, transcript, metadata):
    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()

    prompt = template
    prompt = prompt.replace('{main_speaker}', metadata.get('main_speaker', ''))
    prompt = prompt.replace('{mc}', metadata.get('mc', ''))
    prompt = prompt.replace('{other_speaker}', metadata.get('other_speaker', ''))
    prompt = prompt.replace('{raw_script}', transcript)
    return prompt


def _extract_text(response):
    """response.text가 safety block / MAX_TOKENS 등으로 실패할 수 있어 방어적으로 추출."""
    try:
        return response.text
    except (ValueError, AttributeError):
        pass
    try:
        parts = response.candidates[0].content.parts
        chunks = [p.text for p in parts if getattr(p, 'text', None)]
        return ''.join(chunks) if chunks else None
    except (IndexError, AttributeError):
        return None


def _finish_reason(response):
    try:
        return response.candidates[0].finish_reason
    except (IndexError, AttributeError):
        return 'unknown'


def call_gemini(prompt, api_key, model_tier='pro', auto_fallback=True):
    try:
        from google import genai
    except ImportError:
        raise RuntimeError("google-genai 패키지가 필요합니다: pip install google-genai")

    client = genai.Client(api_key=api_key)

    tiers_to_try = FALLBACK_CHAIN[FALLBACK_CHAIN.index(model_tier):] if auto_fallback else [model_tier]

    for tier in tiers_to_try:
        model_name = GEMINI_MODELS[tier]
        logger.info(f"Gemini 호출: {model_name} ({FREE_TIER_LIMITS[tier]})")
        try:
            response = client.models.generate_content(model=model_name, contents=prompt)
            text = _extract_text(response)
            if text is None:
                reason = _finish_reason(response)
                raise RuntimeError(f"Gemini 응답에 본문 없음 (finish_reason={reason})")
            logger.info(f"Gemini 응답 완료: {model_name} ({len(text):,}자)")
            return text, tier
        except Exception as e:
            err = str(e)
            if '429' in err or 'quota' in err.lower() or 'RESOURCE_EXHAUSTED' in err:
                next_tiers = tiers_to_try[tiers_to_try.index(tier) + 1:]
                if next_tiers:
                    logger.warning(f"{model_name} 할당량 초과 → {GEMINI_MODELS[next_tiers[0]]}으로 폴백")
                    time.sleep(2)
                    continue
                else:
                    raise RuntimeError("Gemini 전 티어 할당량 초과. 내일 다시 시도하거나 API 키를 확인하세요.")
            raise

    raise RuntimeError("Gemini 호출 실패")


def process_with_gemini(pending_item, template_path, api_key, model_tier='pro'):
    transcript_path = pending_item['transcript_path']
    metadata_path = pending_item.get('metadata_path')

    with open(transcript_path, 'r', encoding='utf-8') as f:
        transcript = f.read()

    metadata = pending_item.copy()
    if metadata_path and os.path.exists(metadata_path):
        import json
        with open(metadata_path, 'r', encoding='utf-8') as f:
            metadata.update(json.load(f))

    prompt = build_prompt(template_path, transcript, metadata)
    result_text, used_tier = call_gemini(prompt, api_key, model_tier)
    return result_text, used_tier


def print_gemini_model_info():
    sep = "=" * 50
    print(f"\n{sep}")
    print("Gemini 무료 티어 모델 안내")
    print(f"{sep}")
    for tier, model in GEMINI_MODELS.items():
        print(f"  --gemini-model {tier:<10} {model:<30} ({FREE_TIER_LIMITS[tier]})")
    print(f"\n  미지정 시 pro → thinking → flash 순으로 자동 폴백")
    print(f"{sep}\n")
