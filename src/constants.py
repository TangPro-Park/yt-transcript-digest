"""프로젝트 전역 상수.

여러 모듈에서 공유하는 상수를 한 곳에서 관리한다.
모드 추가 시 이 파일만 수정하면 main.py, plan.py, digest_runner.py에 자동 반영.
"""

TEMPLATES = {
    'heavy':         './templates/deep_analysis.md',
    'medium':        './templates/medium_summary.md',
    'compact':       './templates/compact.md',
    'compact_local': './templates/compact_local.md',
    'shorts':        './templates/shorts.md',
}
