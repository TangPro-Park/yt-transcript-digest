"""--digest-only 모드 실행기.

cache/pending.json을 읽어 LLM 처리만 실행한다.
트랜스크립트 fetch와 channel/기간 인자는 무시한다.

기존 main.py의 _run_*_processing 함수와 _load_env_key는 의존성 주입(DI)으로
받는다. 이렇게 하면 main.py를 import할 필요가 없어 모듈 결합이 약해진다.
"""

import os
import json
import logging
import sys

logger = logging.getLogger(__name__)

PENDING_PATH = './cache/pending.json'

# main.py의 TEMPLATES와 동일하게 유지 (--mode 덮어쓰기 시 template 매핑용)
TEMPLATES = {
    'heavy':         './templates/deep_analysis.md',
    'medium':        './templates/medium_summary.md',
    'compact':       './templates/compact.md',
    'compact_local': './templates/compact_local.md',
    'shorts':        './templates/shorts.md',
}


def run_digest_only(
    cfg,
    mode_override=None,
    llm='claude',
    gemini_model='pro',
    claude_model=None,
    *,
    run_claude,
    run_gemini,
    run_local,
    load_env_key,
    claude_models,
):
    """pending.json 읽어서 LLM 처리만 실행.

    Parameters
    ----------
    cfg : dict
        config.yaml 내용
    mode_override : str | None
        명시되면 manifest의 mode/template를 덮어쓴다. None이면 manifest 그대로.
    llm : 'claude' | 'gemini' | 'local'
    gemini_model : str
    claude_model : str | None
    run_claude, run_gemini, run_local : callable
        main.py의 _run_*_processing 함수 (DI)
    load_env_key : callable
        main.py의 _load_env_key (DI)
    claude_models : dict
        모델 표시용 매핑 (DI)
    """
    if not os.path.exists(PENDING_PATH):
        print(f"오류: {PENDING_PATH}가 없습니다. 먼저 --fetch-only를 실행하세요.")
        sys.exit(1)

    with open(PENDING_PATH, 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    if mode_override:
        if mode_override not in TEMPLATES:
            print(f"오류: 알 수 없는 mode '{mode_override}'")
            sys.exit(1)
        manifest['mode']     = mode_override
        manifest['template'] = TEMPLATES[mode_override]

    pending = manifest.get('pending', [])
    if not pending:
        print("처리할 항목이 없습니다 (pending 비어있음).")
        return None

    sep = "=" * 60
    mode = manifest.get('mode', 'heavy')
    print(f"\n{sep}")
    print(f"[--digest-only] 모드: {mode}  |  LLM: {llm}  |  대기 {len(pending)}개")
    print(f"{sep}")

    if llm == 'claude':
        cm = claude_model
        print(f"Claude 모델: {claude_models.get(cm, cm)}")
        saved = run_claude(manifest, cm)
    elif llm == 'gemini':
        gemini_api_key = load_env_key('GEMINI_API_KEY')
        if not gemini_api_key:
            print("오류: .env에 GEMINI_API_KEY를 설정하세요.")
            sys.exit(1)
        print(f"Gemini 티어: {gemini_model}")
        saved = run_gemini(manifest, gemini_api_key, gemini_model)
    elif llm == 'local':
        if 'local_llm' not in cfg:
            print("오류: config.yaml에 local_llm 섹션이 필요합니다.")
            sys.exit(1)
        saved = run_local(manifest, cfg)
    else:
        print(f"오류: 지원하지 않는 LLM: {llm}")
        sys.exit(1)

    print(f"\n완료: {len(saved)}개 파일 저장")

    # pending.json을 archive로 이동 (cache/digested/{ts}.json)
    from src.digest_archive import archive_pending
    dest = archive_pending(PENDING_PATH)
    if dest:
        print(f"pending.json 아카이브: {dest}")

    return manifest
