"""Fetch run 관리.

한 번의 fetch 실행을 하나의 'run'으로 묶어 cache/fetch_runs.json에 누적 기록한다.
- run_id: 'YYYYMMDDTHHMMSS_{kind}' 형태
- kind:   'popular' | 'range' | 'keyword' | 'latest' | 'single'
- video_ids: 이 run에서 fetch 시도된 영상들 (성공/실패 무관)

이 파일은 추가 전용. registry.py와 독립적이며, plan.py가 이 데이터를 읽어
다이제스트 대상 선정에 활용한다.
"""

import os
import json
import logging
from datetime import datetime
from threading import Lock

logger = logging.getLogger(__name__)

RUNS_PATH = './cache/fetch_runs.json'
_lock = Lock()


def _now_iso():
    return datetime.now().isoformat(timespec='seconds')


def make_run_id(kind):
    """'20260425T173149_popular' 형태의 run_id 생성."""
    ts = datetime.now().strftime('%Y%m%dT%H%M%S')
    return f'{ts}_{kind}'


def _load(path):
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(runs, path):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(runs, f, ensure_ascii=False, indent=2)


def save_run(run_id, kind, channel_url, params, video_ids, runs_path=RUNS_PATH):
    """run을 추가하거나 같은 run_id가 있으면 video_ids를 갱신한다."""
    with _lock:
        runs = _load(runs_path)
        for r in runs:
            if r.get('run_id') == run_id:
                r['video_ids']   = video_ids
                r['channel_url'] = channel_url
                r['params']      = params
                _save(runs, runs_path)
                return
        runs.append({
            'run_id':      run_id,
            'ran_at':      _now_iso(),
            'kind':        kind,
            'channel_url': channel_url,
            'params':      params,
            'video_ids':   video_ids,
        })
        _save(runs, runs_path)


def get_run(run_id, runs_path=RUNS_PATH):
    for r in _load(runs_path):
        if r.get('run_id') == run_id:
            return r
    return None


def latest_run(kind=None, runs_path=RUNS_PATH):
    """가장 최근 run. kind 지정 시 해당 종류 중 최근."""
    runs = _load(runs_path)
    if kind:
        runs = [r for r in runs if r.get('kind') == kind]
    if not runs:
        return None
    return max(runs, key=lambda r: r.get('ran_at', ''))


def load_all_runs(runs_path=RUNS_PATH):
    return _load(runs_path)
