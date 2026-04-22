import logging
import os
from openai import OpenAI

logger = logging.getLogger(__name__)

def process_with_local_llm(transcript_text: str, config: dict) -> str:
    """
    Reads the specified template, formatting it with transcript_text and speaker info,
    then sends it to a local LLM via OpenAI compatible API.
    """
    processing_config = config.get("processing", {})
    llm_config = config.get("local_llm", {})
    speakers_config = config.get("speakers", {})
    
    template_path = processing_config.get("template", "templates/deep_analysis.md")
    
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Template not found at {template_path}")
        
    with open(template_path, 'r', encoding='utf-8') as f:
        template_content = f.read()
        
    # Inject variables
    main_speaker = speakers_config.get("main_speaker", "미상")
    mc = speakers_config.get("mc", "미상")
    other_speaker = speakers_config.get("other_speaker", "없음")
    
    prompt = template_content
    prompt = prompt.replace("{main_speaker}", main_speaker)
    prompt = prompt.replace("{mc}", mc)
    prompt = prompt.replace("{other_speaker}", other_speaker)
    prompt = prompt.replace("{raw_script}", transcript_text)

    # 로컬 전용 템플릿에만 존재하는 분량 파라미터를 사전 계산해 주입.
    # 기존 Claude/Gemini용 템플릿에는 해당 토큰이 없으므로 no-op.
    if "{overview_lines}" in prompt:
        from src.prompt_params import compute_params
        for key, value in compute_params(len(transcript_text)).items():
            prompt = prompt.replace(f"{{{key}}}", str(value))
    
    base_url = llm_config.get("base_url", "http://localhost:11434/v1")
    model = llm_config.get("model", "gemma:7b-instruct")
    temperature = llm_config.get("temperature", 0.1)
    max_tokens = llm_config.get("max_tokens", 4096)
    num_ctx = llm_config.get("num_ctx")

    try:
        logger.info(f"Connecting to local LLM at {base_url} using model {model}...")
        client = OpenAI(
            base_url=base_url,
            api_key="local-dummy-key" # Standard local providers usually accept anything
        )

        extra = {"options": {"num_ctx": num_ctx}} if num_ctx else {}
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra,
        )
        
        result_text = response.choices[0].message.content
        logger.info("Local LLM processing completed successfully.")
        return result_text
        
    except Exception as e:
        logger.error(f"Local LLM processing failed: {str(e)}")
        raise e
