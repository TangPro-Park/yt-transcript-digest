import json
import re
import logging
from datetime import datetime, timezone
from urllib.parse import quote
from urllib.request import urlopen, Request

from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

UNKNOWN_DATE = 'unknown-date'

# API 키 없거나 조회 실패 시 확장 메타 기본값
_EMPTY_RICH_META = {
    'description':      '',
    'tags':             [],
    'chapters':         [],
    'view_count':       0,
    'like_count':       0,
    'topic_categories': [],
}


def _fetch_oembed(video_url):
    """oembed로 title/author_name 조회 (API 키 불필요). 실패 시 None."""
    endpoint = f"https://www.youtube.com/oembed?url={quote(video_url, safe='')}&format=json"
    try:
        with urlopen(Request(endpoint, headers={'User-Agent': 'yt-transcript-digest'}), timeout=5) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        logger.debug(f"oembed 실패: {e}")
        return None


def _parse_channel_url(channel_url):
    patterns = [
        (r'youtube\.com/channel/([UC][a-zA-Z0-9_-]{21,})', 'id'),
        (r'youtube\.com/@([^/?&\s]+)', 'handle'),
        (r'youtube\.com/c/([^/?&\s]+)', 'custom'),
        (r'youtube\.com/user/([^/?&\s]+)', 'user'),
    ]
    for pattern, kind in patterns:
        m = re.search(pattern, channel_url)
        if m:
            return kind, m.group(1)
    raise ValueError(f"인식할 수 없는 채널 URL: {channel_url}")


def _get_channel_id(youtube, channel_url):
    kind, value = _parse_channel_url(channel_url)
    if kind == 'id':
        return value
    if kind == 'handle':
        resp = youtube.channels().list(part='id', forHandle=value).execute()
    else:
        resp = youtube.channels().list(part='id', forUsername=value).execute()
    items = resp.get('items', [])
    if not items:
        raise ValueError(f"채널을 찾을 수 없음: {channel_url}")
    return items[0]['id']


def _parse_duration(iso):
    m = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', iso or '')
    if not m:
        return iso
    h, mn, s = (int(x) if x else 0 for x in m.groups())
    return f"{h}:{mn:02d}:{s:02d}" if h else f"{mn}:{s:02d}"


def _parse_chapters(description: str) -> list:
    """description 텍스트에서 챕터 타임스탬프를 파싱한다.

    '00:00 서론\\n03:42 환율이란?' → [{'seconds': 0, 'title': '서론'}, ...]
    """
    chapters = []
    for m in re.finditer(r'(?:^|\n)(?:(\d+):)?(\d+):(\d+)[ \t]+(.+)', description or ''):
        h  = int(m.group(1) or 0)
        mn = int(m.group(2))
        s  = int(m.group(3))
        chapters.append({'seconds': h * 3600 + mn * 60 + s, 'title': m.group(4).strip()})
    return chapters


def _extract_rich_meta(item: dict) -> dict:
    """videos().list() 응답 단일 item에서 확장 메타데이터를 추출한다."""
    snippet = item.get('snippet', {})
    stats   = item.get('statistics', {})
    topic   = item.get('topicDetails', {})
    desc    = snippet.get('description', '')
    return {
        'description':      desc,
        'tags':             snippet.get('tags', []),
        'chapters':         _parse_chapters(desc),
        'view_count':       int(stats.get('viewCount', 0)),
        'like_count':       int(stats.get('likeCount', 0)),
        'topic_categories': topic.get('topicCategories', []),
    }


def _fetch_video_details(youtube, videos):
    """video_id 배열을 50개씩 batch로 조회해 duration + 확장 메타를 채운다.

    _fetch_durations()를 대체. snippet/statistics/topicDetails를 한 번에 요청.
    """
    if not videos:
        return videos
    ids = [v['video_id'] for v in videos]
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        resp = youtube.videos().list(
            part='snippet,contentDetails,statistics,topicDetails',
            id=','.join(batch),
        ).execute()
        details_map = {
            item['id']: {
                'duration': _parse_duration(item['contentDetails']['duration']),
                **_extract_rich_meta(item),
            }
            for item in resp.get('items', [])
        }
        for v in videos[i:i + 50]:
            d = details_map.get(v['video_id'], {})
            v['duration'] = d.get('duration', v.get('duration'))
            for key in _EMPTY_RICH_META:
                v[key] = d.get(key, _EMPTY_RICH_META[key])
    return videos


def extract_video_id(url):
    """YouTube URL에서 video_id 추출."""
    patterns = [r'(?:v=|/embed/|/shorts/|youtu\.be/)([a-zA-Z0-9_-]{11})']
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    raise ValueError(f"video_id를 추출할 수 없는 URL: {url}")


def get_video_by_url(video_url, api_key=None):
    """단일 영상 URL에서 메타데이터를 가져온다.

    api_key가 없으면 oembed로 기본 필드만 조회하고 확장 메타는 빈 값.
    Returns: dict {video_id, title, published_at, duration, url, channel_name,
                   description, tags, chapters, view_count, like_count, topic_categories}
    """
    video_id = extract_video_id(video_url)
    url = f'https://www.youtube.com/watch?v={video_id}'

    if not api_key:
        logger.info(f"API 키 없음 — oembed로 메타데이터 조회: {video_id}")
        oembed = _fetch_oembed(url) or {}
        return {
            'video_id':     video_id,
            'title':        oembed.get('title', video_id),
            'published_at': UNKNOWN_DATE,
            'duration':     None,
            'url':          url,
            'channel_name': oembed.get('author_name', 'unknown'),
            **_EMPTY_RICH_META,
        }

    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        resp = youtube.videos().list(
            part='snippet,contentDetails,statistics,topicDetails',
            id=video_id,
        ).execute()
        items = resp.get('items', [])
        if not items:
            raise ValueError(f"영상을 찾을 수 없음: {video_id}")

        item    = items[0]
        snippet = item['snippet']
        published = datetime.fromisoformat(snippet['publishedAt'].replace('Z', '+00:00'))

        return {
            'video_id':     video_id,
            'title':        snippet['title'],
            'published_at': published.strftime('%Y-%m-%d'),
            'duration':     _parse_duration(item['contentDetails']['duration']),
            'url':          url,
            'channel_name': snippet.get('channelTitle', 'unknown'),
            **_extract_rich_meta(item),
        }
    except Exception as e:
        logger.warning(f"YouTube API 호출 실패 — oembed로 폴백: {type(e).__name__}: {e}")
        oembed = _fetch_oembed(url) or {}
        return {
            'video_id':     video_id,
            'title':        oembed.get('title', video_id),
            'published_at': UNKNOWN_DATE,
            'duration':     None,
            'url':          url,
            'channel_name': oembed.get('author_name', 'unknown'),
            **_EMPTY_RICH_META,
        }


def get_videos(api_key, channel_url, start_date, end_date, languages=None, max_videos=50):
    """YouTube Data API로 채널의 기간 내 영상 목록을 가져온다.

    Returns: list of {video_id, title, published_at, duration, url, channel_name,
                      description, tags, chapters, view_count, like_count, topic_categories}
    """
    youtube = build('youtube', 'v3', developerKey=api_key)
    channel_id = _get_channel_id(youtube, channel_url)
    logger.info(f"채널 ID: {channel_id}")

    resp = youtube.channels().list(part='contentDetails,snippet', id=channel_id).execute()
    channel_item     = resp['items'][0]
    uploads_playlist = channel_item['contentDetails']['relatedPlaylists']['uploads']
    channel_name     = channel_item['snippet']['title']

    start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end_dt   = datetime.fromisoformat(end_date).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)

    videos, next_page, stop = [], None, False
    while not stop and len(videos) < max_videos:
        kwargs = dict(part='snippet', playlistId=uploads_playlist, maxResults=50)
        if next_page:
            kwargs['pageToken'] = next_page

        resp = youtube.playlistItems().list(**kwargs).execute()
        for item in resp.get('items', []):
            snippet      = item['snippet']
            published    = datetime.fromisoformat(snippet['publishedAt'].replace('Z', '+00:00'))
            if published < start_dt:
                stop = True
                break
            if published <= end_dt:
                video_id = snippet['resourceId']['videoId']
                videos.append({
                    'video_id':     video_id,
                    'title':        snippet['title'],
                    'published_at': published.strftime('%Y-%m-%d'),
                    'url':          f'https://www.youtube.com/watch?v={video_id}',
                    'duration':     None,
                    'channel_name': channel_name,
                    **_EMPTY_RICH_META,
                })
                if len(videos) >= max_videos:
                    stop = True
                    break

        next_page = resp.get('nextPageToken')
        if not next_page:
            break

    logger.info(f"기간 내 영상: {len(videos)}개")
    return _fetch_video_details(youtube, videos)


def _get_channel_info(youtube, channel_url):
    """채널 ID, 채널명, uploads 플레이리스트를 한 번에 반환."""
    channel_id = _get_channel_id(youtube, channel_url)
    resp = youtube.channels().list(part='contentDetails,snippet', id=channel_id).execute()
    item = resp['items'][0]
    return (
        channel_id,
        item['snippet']['title'],
        item['contentDetails']['relatedPlaylists']['uploads'],
    )


def get_latest_unprocessed(api_key, channel_url, processed_ids, max_check=30):
    """채널 최신 영상 중 processed_ids에 없는 첫 번째 영상을 반환.

    Returns: list (0개 또는 1개)
    """
    youtube = build('youtube', 'v3', developerKey=api_key)
    _, channel_name, uploads_playlist = _get_channel_info(youtube, channel_url)

    next_page, checked = None, 0
    while checked < max_check:
        kwargs = dict(part='snippet', playlistId=uploads_playlist, maxResults=min(50, max_check - checked))
        if next_page:
            kwargs['pageToken'] = next_page

        resp = youtube.playlistItems().list(**kwargs).execute()
        for item in resp.get('items', []):
            snippet  = item['snippet']
            video_id = snippet['resourceId']['videoId']
            checked += 1
            if video_id not in processed_ids:
                published = datetime.fromisoformat(snippet['publishedAt'].replace('Z', '+00:00'))
                video = {
                    'video_id':     video_id,
                    'title':        snippet['title'],
                    'published_at': published.strftime('%Y-%m-%d'),
                    'url':          f'https://www.youtube.com/watch?v={video_id}',
                    'duration':     None,
                    'channel_name': channel_name,
                    **_EMPTY_RICH_META,
                }
                logger.info(f"미처리 최신 영상 발견: {snippet['title']}")
                return _fetch_video_details(youtube, [video])

        next_page = resp.get('nextPageToken')
        if not next_page:
            break

    logger.info("미처리 영상 없음")
    return []


def get_popular_videos(api_key, channel_url, max_results=50):
    """채널의 인기 영상을 조회수 내림차순으로 가져온다.

    search.list API 사용 (100 quota units/call).
    Returns: list of {video_id, title, published_at, duration, url, channel_name, ...}
    """
    youtube = build('youtube', 'v3', developerKey=api_key)
    channel_id, channel_name, _ = _get_channel_info(youtube, channel_url)

    videos, next_page = [], None
    while len(videos) < max_results:
        kwargs = dict(
            part='snippet',
            channelId=channel_id,
            type='video',
            order='viewCount',
            videoDuration='medium',
            maxResults=min(50, max_results - len(videos)),
        )
        if next_page:
            kwargs['pageToken'] = next_page

        resp = youtube.search().list(**kwargs).execute()
        for item in resp.get('items', []):
            if item['id'].get('kind') != 'youtube#video':
                continue
            snippet   = item['snippet']
            published = datetime.fromisoformat(snippet['publishedAt'].replace('Z', '+00:00'))
            videos.append({
                'video_id':     item['id']['videoId'],
                'title':        snippet['title'],
                'published_at': published.strftime('%Y-%m-%d'),
                'url':          f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                'duration':     None,
                'channel_name': channel_name,
                **_EMPTY_RICH_META,
            })

        next_page = resp.get('nextPageToken')
        if not next_page or len(videos) >= max_results:
            break

    logger.info(f"인기순 영상: {len(videos)}개")
    return _fetch_video_details(youtube, videos[:max_results])


def get_popular_videos_by_stats(api_key, channel_url, top=10, scan_limit=200):
    """업로드 목록 최근 scan_limit개를 통계 기준으로 정렬해 상위 top개를 반환.

    search.list 대신 playlistItems + videos.statistics를 사용해 정확한 조회수 기반 정렬.
    쇼츠(#쇼츠/#shorts 제목, 또는 1분 미만)는 자동 제외.
    """
    youtube = build('youtube', 'v3', developerKey=api_key)
    _, channel_name, uploads_playlist = _get_channel_info(youtube, channel_url)

    raw, next_page = [], None
    while len(raw) < scan_limit:
        kwargs = dict(part='snippet', playlistId=uploads_playlist, maxResults=50)
        if next_page:
            kwargs['pageToken'] = next_page
        resp = youtube.playlistItems().list(**kwargs).execute()
        for item in resp.get('items', []):
            snippet  = item['snippet']
            video_id = snippet['resourceId']['videoId']
            published = datetime.fromisoformat(snippet['publishedAt'].replace('Z', '+00:00'))
            raw.append({
                'video_id':     video_id,
                'title':        snippet['title'],
                'published_at': published.strftime('%Y-%m-%d'),
                'url':          f'https://www.youtube.com/watch?v={video_id}',
                'duration':     None,
                'channel_name': channel_name,
                **_EMPTY_RICH_META,
            })
        next_page = resp.get('nextPageToken')
        if not next_page:
            break

    _fetch_video_details(youtube, raw)  # view_count, duration, 확장 메타 일괄 보강

    def _is_shorts(v):
        title = v.get('title', '')
        dur   = v.get('duration') or ''
        if '#쇼츠' in title or '#shorts' in title.lower():
            return True
        m = re.match(r'^(?:(\d+):)?(\d+):(\d+)$', dur)
        if m:
            h, mn = int(m.group(1) or 0), int(m.group(2))
            return h == 0 and mn < 1
        return False

    normals = [v for v in raw if not _is_shorts(v)]
    normals.sort(key=lambda v: v['view_count'], reverse=True)
    logger.info(f"인기순 영상 (최근 {len(raw)}개 스캔 / 일반 {len(normals)}개): 상위 {top}개 반환")
    return normals[:top]


def get_videos_by_keyword(api_key, channel_url, keyword, start_date=None, end_date=None, max_results=50):
    """채널에서 키워드가 포함된 영상 목록을 가져온다.

    search.list API 사용 (100 quota units/call).
    Returns: list of {video_id, title, published_at, duration, url, channel_name, ...}
    """
    youtube = build('youtube', 'v3', developerKey=api_key)
    channel_id, channel_name, _ = _get_channel_info(youtube, channel_url)

    kwargs = dict(
        part='snippet',
        channelId=channel_id,
        q=keyword,
        type='video',
        maxResults=min(50, max_results),
        order='date',
    )
    if start_date:
        kwargs['publishedAfter'] = f"{start_date}T00:00:00Z"
    if end_date:
        kwargs['publishedBefore'] = f"{end_date}T23:59:59Z"

    videos = []
    while len(videos) < max_results:
        resp = youtube.search().list(**kwargs).execute()
        for item in resp.get('items', []):
            if item['id'].get('kind') != 'youtube#video':
                continue
            snippet   = item['snippet']
            published = datetime.fromisoformat(snippet['publishedAt'].replace('Z', '+00:00'))
            videos.append({
                'video_id':     item['id']['videoId'],
                'title':        snippet['title'],
                'published_at': published.strftime('%Y-%m-%d'),
                'url':          f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                'duration':     None,
                'channel_name': channel_name,
                **_EMPTY_RICH_META,
            })
        next_page = resp.get('nextPageToken')
        if not next_page or len(videos) >= max_results:
            break
        kwargs['pageToken'] = next_page

    logger.info(f"키워드 '{keyword}' 검색 결과: {len(videos)}개")
    return _fetch_video_details(youtube, videos[:max_results])
