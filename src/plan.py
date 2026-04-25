"""레지스트리에서 다이제스트 계획(pending.json)을 생성한다.

fetch run의 video_ids 순서를 그대로 사용한다 (popular run이면 인기순).
이미 같은 mode로 다이제스트된 영상은 기본 제외(skip_already=True).
"""

import os
import json
import logging

from src import registry, fetch_runs
from src.storage import sanitize_dirname

logger = logging.getLogger(__name__)

PENDING_PATH = './cache/pending.json'

TEMPLATES = {
    'heavy':         './templates/deep_analysis.md',
    'medium':        './templates/medium_summary.md',
    'compact':       './templates/compact.md',
    'compact_local': './templates/compact_local.md',
    'shorts':        './templates/shorts.md',
}


def _already_digested_with_mode(entry, mode):
    for d in (entry.get('digests') or []):
        if d.get('mode') == mode:
            return True
    return False


def plan_from_registry(
    cfg,
    from_run='latest',
    from_run_kind=None,
    top=None,
    mode='heavy',
    skip_already=True,
    pending_path=PENDING_PATH,
):
    """run을 골라 video_ids 순서대로 pending.json을 작성.

    Parameters
    ----------
    from_run : 'latest' | run_id 문자열
    from_run_kind : kind 필터. 'latest'와 함께 쓰면 해당 kind 중 최신 선택
    top : 상위 N개만. None이면 전체
    mode : digest mode
    skip_already : True면 같은 mode로 이미 처리된 영상 제외

    Returns
    -------
    dict : 작성된 manifest, 또는 비었으면 None
    """
    if mode not in TEMPLATES:
        raise ValueError(f"unknown mode: {mode}")

    if from_run == 'latest':
        run = fetch_runs.latest_run(kind=from_run_kind)
    else:
        run = fetch_runs.get_run(from_run)

    if not run:
        print(f"오류: fetch run을 찾을 수 없습니다 (from_run={from_run}, kind={from_run_kind})")
        return None

    video_ids = run.get('video_ids', [])
    if not video_ids:
        print(f"오류: run '{run['run_id']}'에 video_ids가 없습니다.")
        return None

    pending = []
    skipped_already = []
    skipped_unfetched = []
    for vid in video_ids:
        entry = registry.find(vid)
        if not entry:
            skipped_unfetched.append(vid)
            continue
        if entry.get('status') != 'fetched':
            skipped_unfetched.append(vid)
            continue
        if skip_already and _already_digested_with_mode(entry, mode):
            skipped_already.append(vid)
            continue
        pending.append({
            'video_id':        entry['video_id'],
            'channel_name':    entry.get('channel_name', ''),
            'title':           entry.get('title', ''),
            'published_at':    entry.get('published_at', ''),
            'url':             entry.get('url', ''),
            'duration':        entry.get('duration', ''),
            'transcript_path': entry.get('transcript_path'),
            'metadata_path':   entry.get('metadata_path'),
        })
        if top and len(pending) >= top:
            break

    if not pending:
        print("계획 결과 비어있음. (이미 처리됐거나 fetched 상태가 아님)")
        return None

    output_base  = cfg['output']['base_dir']
    channel_name = pending[0].get('channel_name', '')
    channel_dir  = os.path.join(output_base, sanitize_dirname(channel_name))
    subdir = '인기' if run.get('kind') == 'popular' else ''
    manifest = {
        'mode':         mode,
        'template':     TEMPLATES[mode],
        'channel_name': channel_name,
        'channel_url':  run.get('channel_url', ''),
        'channel_dir':  channel_dir,
        'output_base':  output_base,
        'subdir':       subdir,
        'pending':      pending,
        'skipped':      [],
        'source_run':   run['run_id'],
    }

    os.makedirs(os.path.dirname(pending_path) or '.', exist_ok=True)
    with open(pending_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"계획 작성: {pending_path}")
    print(f"  source_run:    {run['run_id']} ({run.get('kind')})")
    print(f"  mode:          {mode}")
    print(f"  pending:       {len(pending)}개")
    if skipped_already:
        print(f"  이미 처리됨:   {len(skipped_already)}개 제외")
    if skipped_unfetched:
        print(f"  fetch 안됨:    {len(skipped_unfetched)}개 제외")
    return manifest
