import json
import re
import logging
from datetime import datetime, timezone
from urllib.parse import quote
from urllib.request import urlopen, Request

from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

UNKNOWN_DATE = 'unknown-date'


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


def _fetch_durations(youtube, videos):
    if not videos:
        return videos
    ids = [v['video_id'] for v in videos]
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        resp = youtube.videos().list(part='contentDetails', id=','.join(batch)).execute()
        dur_map = {item['id']: item['contentDetails']['duration'] for item in resp.get('items', [])}
        for v in videos[i:i + 50]:
            v['duration'] = _parse_duration(dur_map.get(v['video_id'], 'PT0S'))
    return videos


def extract_video_id(url):
    """YouTube URL에서 video_id 추출."""
    patterns = [
        r'(?:v=|/embed/|/shorts/|youtu\.be/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    raise ValueError(f"video_id를 추출할 수 없는 URL: {url}")


def get_video_by_url(video_url, api_key=None):
    """단일 영상 URL에서 메타데이터를 가져온다.

    api_key가 없으면 video_id와 URL만 포함한 최소 메타데이터를 반환.
    Returns: dict {video_id, title, published_at, duration, url, channel_name}
    """
    video_id = extract_video_id(video_url)
    url = f'https://www.youtube.com/watch?v={video_id}'

    if not api_key:
        logger.info(f"API 키 없음 — oembed로 메타데이터 조회: {video_id}")
        oembed = _fetch_oembed(url) or {}
        return {
            'video_id': video_id,
            'title': oembed.get('title', video_id),
            'published_at': UNKNOWN_DATE,
            'duration': None,
            'url': url,
            'channel_name': oembed.get('author_name', 'unknown'),
        }

    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        resp = youtube.videos().list(part='snippet,contentDetails', id=video_id).execute()
        items = resp.get('items', [])
        if not items:
            raise ValueError(f"영상을 찾을 수 없음: {video_id}")

        item = items[0]
        snippet = item['snippet']
        published = datetime.fromisoformat(snippet['publishedAt'].replace('Z', '+00:00'))

        return {
            'video_id': video_id,
            'title': snippet['title'],
            'published_at': published.strftime('%Y-%m-%d'),
            'duration': _parse_duration(item['contentDetails']['duration']),
            'url': url,
            'channel_name': snippet.get('channelTitle', 'unknown'),
        }
    except Exception as e:
        logger.warning(f"YouTube API 호출 실패 — oembed로 폴백: {type(e).__name__}: {e}")
        oembed = _fetch_oembed(url) or {}
        return {
            'video_id': video_id,
            'title': oembed.get('title', video_id),
            'published_at': UNKNOWN_DATE,
            'duration': None,
            'url': url,
            'channel_name': oembed.get('author_name', 'unknown'),
        }


def get_videos(api_key, channel_url, start_date, end_date, languages=None, max_videos=50):
    """YouTube Data API로 채널의 기간 내 영상 목록을 가져온다.

    Returns: list of {video_id, title, published_at, duration, url, channel_name}
    """
    youtube = build('youtube', 'v3', developerKey=api_key)
    channel_id = _get_channel_id(youtube, channel_url)
    logger.info(f"채널 ID: {channel_id}")

    resp = youtube.channels().list(part='contentDetails,snippet', id=channel_id).execute()
    channel_item = resp['items'][0]
    uploads_playlist = channel_item['contentDetails']['relatedPlaylists']['uploads']
    channel_name = channel_item['snippet']['title']

    start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end_date).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)

    videos = []
    next_page = None
    stop = False

    while not stop and len(videos) < max_videos:
        kwargs = dict(part='snippet', playlistId=uploads_playlist, maxResults=50)
        if next_page:
            kwargs['pageToken'] = next_page

        resp = youtube.playlistItems().list(**kwargs).execute()

        for item in resp.get('items', []):
            snippet = item['snippet']
            published_str = snippet['publishedAt'].replace('Z', '+00:00')
            published = datetime.fromisoformat(published_str)

            if published < start_dt:
                stop = True
                break

            if published <= end_dt:
                video_id = snippet['resourceId']['videoId']
                videos.append({
                    'video_id': video_id,
                    'title': snippet['title'],
                    'published_at': published.strftime('%Y-%m-%d'),
                    'url': f'https://www.youtube.com/watch?v={video_id}',
                    'duration': None,
                    'channel_name': channel_name,
                })

                if len(videos) >= max_videos:
                    stop = True
                    break

        next_page = resp.get('nextPageToken')
        if not next_page:
            break

    logger.info(f"기간 내 영상: {len(videos)}개")
    return _fetch_durations(youtube, videos)


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

    next_page = None
    checked = 0

    while checked < max_check:
        kwargs = dict(part='snippet', playlistId=uploads_playlist, maxResults=min(50, max_check - checked))
        if next_page:
            kwargs['pageToken'] = next_page

        resp = youtube.playlistItems().list(**kwargs).execute()

        for item in resp.get('items', []):
            snippet = item['snippet']
            video_id = snippet['resourceId']['videoId']
            checked += 1

            if video_id not in processed_ids:
                published = datetime.fromisoformat(snippet['publishedAt'].replace('Z', '+00:00'))
                video = {
                    'video_id': video_id,
                    'title': snippet['title'],
                    'published_at': published.strftime('%Y-%m-%d'),
                    'url': f'https://www.youtube.com/watch?v={video_id}',
                    'duration': None,
                    'channel_name': channel_name,
                }
                logger.info(f"미처리 최신 영상 발견: {snippet['title']}")
                return _fetch_durations(youtube, [video])

        next_page = resp.get('nextPageToken')
        if not next_page:
            break

    logger.info("미처리 영상 없음")
    return []


def get_videos_by_keyword(api_key, channel_url, keyword, start_date=None, end_date=None, max_results=50):
    """채널에서 키워드가 포함된 영상 목록을 가져온다.

    search.list API 사용 (100 quota units/call).
    Returns: list of {video_id, title, published_at, duration, url, channel_name}
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
            snippet = item['snippet']
            published = datetime.fromisoformat(snippet['publishedAt'].replace('Z', '+00:00'))
            videos.append({
                'video_id': item['id']['videoId'],
                'title': snippet['title'],
                'published_at': published.strftime('%Y-%m-%d'),
                'url': f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                'duration': None,
                'channel_name': channel_name,
            })

        next_page = resp.get('nextPageToken')
        if not next_page or len(videos) >= max_results:
            break
        kwargs['pageToken'] = next_page

    logger.info(f"키워드 '{keyword}' 검색 결과: {len(videos)}개")
    return _fetch_durations(youtube, videos[:max_results])
