import logging
import subprocess

logger = logging.getLogger(__name__)

CLAUDE_MODELS = {
    'haiku':  'claude-haiku-4-5-20251001',
    'sonnet': 'claude-sonnet-4-6',
    'opus':   'claude-opus-4-7',
}
DEFAULT_MODEL = 'haiku'


def process_with_claude_cli(item, template_path, model_alias=DEFAULT_MODEL):
    """claude CLI subprocess로 트랜스크립트를 처리한다.

    prompt를 stdin으로 전달하므로 트랜스크립트 길이 제한 없음.
    """
    model_id = CLAUDE_MODELS.get(model_alias, model_alias)

    with open(template_path, 'r', encoding='utf-8') as f:
        prompt = f.read()

    with open(item['transcript_path'], 'r', encoding='utf-8') as f:
        transcript = f.read()

    prompt = prompt.replace('{raw_script}', transcript)
    prompt = prompt.replace('{main_speaker}', item.get('main_speaker', ''))
    prompt = prompt.replace('{mc}', item.get('mc', ''))
    prompt = prompt.replace('{other_speaker}', item.get('other_speaker', ''))

    title = item.get('title', item['video_id'])
    logger.info(f"claude CLI [{model_id}] 호출: {title}")

    result = subprocess.run(
        ['claude', '--model', model_id, '--print'],
        input=prompt,
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=600,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"claude CLI 오류 [{result.returncode}]:\n{result.stderr[:500]}"
        )

    return result.stdout.strip()
