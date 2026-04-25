"""트랜스크립트 fetch 작업의 전역 레지스트리.

cache/transcripts.json 한 파일로 통합 관리한다.
- discover 시점: status='queued', queued_at 기록
- fetch 성공:    status='fetched', fetched_at + transcript_path 기록
- fetch 실패:    status='failed', failed_at + error 기록

기존 pending.json(현재 배치 manifest)과 .processed.json(digest 완료 추적)은
변경하지 않는다. 이 레지스트리는 추가 전용이며 기존 로직이 읽지 않는다.
"""

import os
import json
import logging
from datetime import datetime
from threading import Lock

logger = logging.getLogger(__name__)

REGISTRY_PATH = './cache/transcripts.json'
_lock = Lock()


def _now():
    return datetime.now().isoformat(timespec='seconds')


def _load(path):
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(entries, path):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def _find_idx(entries, video_id):
    for i, e in enumerate(entries):
        if e.get('video_id') == video_id:
            return i
    return -1


def add_queued(video, registry_path=REGISTRY_PATH, run_id=None):
    """발견된 영상을 queued 상태로 등록.

    이미 등록된 영상이면 status는 그대로 두고 run_id만 fetch_runs에 누적한다.
    같은 run_id가 이미 있으면 중복 추가하지 않는다.
    """
    with _lock:
        entries = _load(registry_path)
        idx = _find_idx(entries, video['video_id'])
        if idx >= 0:
            if run_id:
                runs = entries[idx].get('fetch_runs') or []
                if run_id not in runs:
                    runs.append(run_id)
                    entries[idx]['fetch_runs'] = runs
                    _save(entries, registry_path)
            return
        entries.append({
            'video_id':        video['video_id'],
            'channel_name':    video.get('channel_name', ''),
            'title':           video.get('title', ''),
            'published_at':    video.get('published_at', ''),
            'url':             video.get('url', ''),
            'duration':        video.get('duration', ''),
            'status':          'queued',
            'queued_at':       _now(),
            'fetched_at':      None,
            'failed_at':       None,
            'transcript_path': None,
            'metadata_path':   None,
            'error':           None,
            'fetch_runs':      [run_id] if run_id else [],
        })
        _save(entries, registry_path)


def mark_fetched(video_id, transcript_path, metadata_path, registry_path=REGISTRY_PATH):
    """fetch 성공 시 호출. queued entry가 없으면 방어적으로 새로 생성."""
    with _lock:
        entries = _load(registry_path)
        idx = _find_idx(entries, video_id)
        if idx < 0:
            entries.append({'video_id': video_id, 'queued_at': _now()})
            idx = len(entries) - 1
        entries[idx].update({
            'status':          'fetched',
            'fetched_at':      _now(),
            'transcript_path': transcript_path,
            'metadata_path':   metadata_path,
            'error':           None,
        })
        _save(entries, registry_path)


def mark_failed(video_id, error, registry_path=REGISTRY_PATH):
    """fetch 실패 시 호출."""
    with _lock:
        entries = _load(registry_path)
        idx = _find_idx(entries, video_id)
        if idx < 0:
            entries.append({'video_id': video_id, 'queued_at': _now()})
            idx = len(entries) - 1
        entries[idx].update({
            'status':    'failed',
            'failed_at': _now(),
            'error':     str(error) if error else 'unknown',
        })
        _save(entries, registry_path)


def mark_digested(video_id, mode, llm, model, output_path, registry_path=REGISTRY_PATH):
    """digest(LLM 처리) 실행 후 호출. entry의 digests 배열에 누적한다.

    같은 영상을 다른 모드로 재처리하면 새 항목이 append된다.
    가장 최근 처리는 entry['digests'][-1]로 조회 가능.
    """
    with _lock:
        entries = _load(registry_path)
        idx = _find_idx(entries, video_id)
        if idx < 0:
            entries.append({'video_id': video_id, 'queued_at': _now()})
            idx = len(entries) - 1
        entry = entries[idx]
        digests = entry.get('digests') or []
        digests.append({
            'digested_at': _now(),
            'mode':        mode,
            'llm':         llm,
            'model':       model,
            'output_path': output_path,
        })
        entry['digests'] = digests
        _save(entries, registry_path)


def load_all(registry_path=REGISTRY_PATH):
    return _load(registry_path)


def find(video_id, registry_path=REGISTRY_PATH):
    entries = _load(registry_path)
    idx = _find_idx(entries, video_id)
    return entries[idx] if idx >= 0 else None
