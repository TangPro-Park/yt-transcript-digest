import glob
import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)


def _find_claude_exe():
    """claude 실행파일 경로를 찾는다. PATH 우선, 없으면 VS Code 확장 경로 탐색."""
    if shutil.which('claude'):
        return 'claude'
    import os
    home = os.path.expanduser('~')
    patterns = [
        os.path.join(home, '.antigravity', 'extensions', 'anthropic.claude-code-*', 'resources', 'native-binary', 'claude.exe'),
        os.path.join(home, 'AppData', 'Local', 'Packages', 'Claude_*', 'LocalCache', 'Roaming', 'Claude', 'claude-code', '*', 'claude.exe'),
    ]
    candidates = []
    for p in patterns:
        candidates.extend(glob.glob(p))
    if candidates:
        candidates.sort(reverse=True)
        return candidates[0]
    return 'claude'

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

    claude_exe = _find_claude_exe()
    logger.info(f"claude 실행파일: {claude_exe}")
    result = subprocess.run(
        [
            claude_exe,
            '--model', model_id,
            '--print',
            '--tools', '',
            '--system-prompt', '당신은 텍스트 생성기입니다. 도구 사용, 파일 쓰기, 질문, 승인 요청 없이 주어진 지시에 따라 마크다운 문서를 stdout으로 출력하기만 합니다.',
        ],
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
