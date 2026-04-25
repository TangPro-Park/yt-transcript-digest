"""다이제스트 완료 후 pending.json을 archive로 이동.

cache/pending.json은 '현재 진행 중인 다이제스트 계획'만 담는 transient queue.
처리 완료 시 cache/digested/{ts}.json으로 이동시켜 이력으로 남긴다.
"""

import os
import json
import shutil
from datetime import datetime

ARCHIVE_DIR = './cache/digested'


def archive_pending(pending_path, archive_dir=ARCHIVE_DIR):
    """pending.json을 archive_dir/{ts}.json으로 이동.

    이동 후 pending.json은 삭제된다. 파일이 없으면 no-op.
    """
    if not os.path.exists(pending_path):
        return None
    os.makedirs(archive_dir, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%dT%H%M%S')
    dest = os.path.join(archive_dir, f'{ts}.json')
    shutil.move(pending_path, dest)
    return dest


def load_archive(name, archive_dir=ARCHIVE_DIR):
    """archive_dir/{name}을 읽어 반환. .json 자동 부착."""
    if not name.endswith('.json'):
        name = name + '.json'
    path = os.path.join(archive_dir, name)
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def list_archives(archive_dir=ARCHIVE_DIR):
    if not os.path.exists(archive_dir):
        return []
    return sorted(os.listdir(archive_dir))
