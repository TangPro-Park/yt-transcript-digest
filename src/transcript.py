import os
import json
import logging
import xml.etree.ElementTree as ET
import html as html_module
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)
try:
    from youtube_transcript_api._errors import IpBlocked
except ImportError:
    IpBlocked = None

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
        if IpBlocked and isinstance(e, IpBlocked):
            logger.warning(f"IpBlocked — v0 폴백 시도: {video_id}")
            return fetch_transcript_v0(video_id, languages=languages, cache_dir=cache_dir, metadata=metadata)
        logger.error(f"트랜스크립트 일시 오류 [{video_id}]: {type(e).__name__}: {e}")
        return None


def fetch_transcript_v0(video_id, languages=None, cache_dir=CACHE_DIR, metadata=None):
    """페이지 직접 파싱으로 트랜스크립트를 가져온다 (innertube 우회 폴백).

    ytInitialPlayerResponse.captionTracks → timedtext XML 직접 요청 방식.
    IpBlocked 시 fetch_transcript()가 자동으로 이 함수로 폴백한다.
    """
    import requests

    if languages is None:
        languages = ['ko', 'en']

    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f'{video_id}.txt')

    if metadata:
        save_metadata(video_id, metadata, cache_dir)

    if os.path.exists(cache_path):
        logger.info(f"캐시 사용(v0): {video_id}")
        with open(cache_path, 'r', encoding='utf-8') as f:
            return f.read()

    session = requests.Session()
    session.headers.update({
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/124.0.0.0 Safari/537.36'
        ),
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
    })
    try:
        resp = session.get(f'https://www.youtube.com/watch?v={video_id}', timeout=15)
        resp.raise_for_status()

        marker = 'ytInitialPlayerResponse = '
        pos = resp.text.find(marker)
        if pos == -1:
            logger.warning(f"ytInitialPlayerResponse 없음 [{video_id}]")
            return None
        pos += len(marker)

        decoder = json.JSONDecoder()
        player_response, _ = decoder.raw_decode(resp.text, pos)

        tracks = (
            player_response
            .get('captions', {})
            .get('playerCaptionsTracklistRenderer', {})
            .get('captionTracks', [])
        )
        if not tracks:
            logger.warning(f"captionTracks 없음 [{video_id}]")
            return None

        track = None
        for lang in languages:
            for t in tracks:
                if t.get('languageCode', '').startswith(lang):
                    track = t
                    break
            if track:
                break
        if not track:
            track = tracks[0]

        xml_resp = session.get(track['baseUrl'], timeout=15)
        xml_resp.raise_for_status()

        root = ET.fromstring(xml_resp.content)
        lines = []
        for elem in root.iter('text'):
            raw = html_module.unescape(elem.text or '')
            raw = raw.replace('\n', ' ').strip()
            if raw:
                lines.append(raw)

        text = '\n'.join(lines)
        with open(cache_path, 'w', encoding='utf-8') as f:
            f.write(text)
        logger.info(
            f"트랜스크립트(v0) 저장 [{track.get('languageCode')}]: {video_id} ({len(text):,}자)"
        )
        return text

    except Exception as e:
        logger.error(f"트랜스크립트 v0 오류 [{video_id}]: {type(e).__name__}: {e}")
        return None
