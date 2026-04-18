import os
import json
import logging
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

logger = logging.getLogger(__name__)

CACHE_DIR = './cache/transcripts'
_api = YouTubeTranscriptApi()


def save_metadata(video_id, metadata, cache_dir=CACHE_DIR):
    """메타데이터를 {video_id}.json으로 저장한다."""
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f'{video_id}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


def load_metadata(video_id, cache_dir=CACHE_DIR):
    """저장된 메타데이터를 반환한다. 없으면 None."""
    path = os.path.join(cache_dir, f'{video_id}.json')
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def fetch_transcript(video_id, languages=None, cache_dir=CACHE_DIR, metadata=None):
    """트랜스크립트를 가져와 캐시에 저장한다. 없으면 None 반환.

    metadata가 제공되면 {video_id}.json에 함께 저장한다.
    """
    if languages is None:
        languages = ['ko', 'en']

    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f'{video_id}.txt')

    # 메타데이터는 항상 최신으로 덮어씀 (제목 등이 바뀔 수 있으므로)
    if metadata:
        save_metadata(video_id, metadata, cache_dir)

    if os.path.exists(cache_path):
        logger.info(f"캐시 사용: {video_id}")
        with open(cache_path, 'r', encoding='utf-8') as f:
            return f.read()

    try:
        fetched = _api.fetch(video_id, languages=languages)
        text = '\n'.join(snippet.text for snippet in fetched)

        with open(cache_path, 'w', encoding='utf-8') as f:
            f.write(text)

        logger.info(f"트랜스크립트 저장: {video_id} ({len(text):,}자)")
        return text

    except NoTranscriptFound:
        # 요청 언어가 없을 때 — 가용 언어로 폴백 시도
        try:
            transcript_list = _api.list(video_id)
            transcript = next(iter(transcript_list))
            fetched = transcript.fetch()
            text = '\n'.join(snippet.text for snippet in fetched)
            with open(cache_path, 'w', encoding='utf-8') as f:
                f.write(text)
            logger.info(f"폴백 트랜스크립트 저장 [{transcript.language_code}]: {video_id} ({len(text):,}자)")
            return text
        except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable, StopIteration) as e2:
            logger.warning(f"가용 트랜스크립트 없음 [{video_id}]: {e2}")
            return None

    except (TranscriptsDisabled, VideoUnavailable) as e:
        logger.warning(f"트랜스크립트 비활성/영상 불가 [{video_id}]: {e}")
        return None

    except Exception as e:
        # 네트워크/IP 블록/파싱 오류 — 캐시 남기지 않고 상위로 전파 가능하도록 명시적 로그
        logger.error(f"트랜스크립트 일시 오류 [{video_id}]: {type(e).__name__}: {e}")
        return None
