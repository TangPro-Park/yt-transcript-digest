"""매억남 채널 탐색 + 라이브 다시보기 트랜스크립트 테스트"""
import os, sys, json
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()

api_key = os.getenv('YOUTUBE_API_KEY')
if not api_key or api_key.startswith('your_'):
    print("ERROR: YOUTUBE_API_KEY not set")
    sys.exit(1)

from googleapiclient.discovery import build
youtube = build('youtube', 'v3', developerKey=api_key)

# 1. 채널 정보
channel_url = "https://www.youtube.com/@-1maeuknam435"
handle = "-1maeuknam435"

# forHandle로 채널 조회
resp = youtube.channels().list(part='snippet,contentDetails,statistics', forHandle=handle).execute()
if not resp.get('items'):
    # forUsername 시도
    resp = youtube.channels().list(part='snippet,contentDetails,statistics', forUsername=handle).execute()

if not resp.get('items'):
    print(f"채널을 찾을 수 없습니다: {handle}")
    sys.exit(1)

ch = resp['items'][0]
print(f"=== 채널 정보 ===")
print(f"  이름: {ch['snippet']['title']}")
print(f"  구독자: {ch['statistics'].get('subscriberCount', '비공개')}")
print(f"  총 영상 수: {ch['statistics'].get('videoCount', '?')}")
print(f"  업로드 플레이리스트: {ch['contentDetails']['relatedPlaylists']['uploads']}")

uploads_pl = ch['contentDetails']['relatedPlaylists']['uploads']

# 2. 최근 영상 5개 가져오기
resp2 = youtube.playlistItems().list(
    part='snippet', playlistId=uploads_pl, maxResults=5
).execute()

print(f"\n=== 최근 영상 5개 ===")
test_ids = []
for i, item in enumerate(resp2['items'], 1):
    s = item['snippet']
    vid = s['resourceId']['videoId']
    title = s['title']
    pub = s['publishedAt'][:10]
    test_ids.append(vid)
    print(f"  {i}. [{pub}] {title}")
    print(f"     https://www.youtube.com/watch?v={vid}")

# 3. 각 영상의 liveBroadcastContent + duration 확인
if test_ids:
    vresp = youtube.videos().list(
        part='contentDetails,liveStreamingDetails,snippet',
        id=','.join(test_ids)
    ).execute()
    print(f"\n=== 영상 상세 (라이브 여부 + 길이) ===")
    for v in vresp['items']:
        vid = v['id']
        title = v['snippet']['title'][:50]
        dur = v['contentDetails']['duration']
        live = v['snippet'].get('liveBroadcastContent', 'none')
        has_live_detail = 'liveStreamingDetails' in v
        print(f"  {vid} | {dur} | live={live} | liveDetails={has_live_detail} | {title}")

# 4. 트랜스크립트 테스트 (첫 번째 영상)
print(f"\n=== 트랜스크립트 테스트 ===")
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled, VideoUnavailable
try:
    from youtube_transcript_api._errors import IpBlocked
except ImportError:
    IpBlocked = None

api = YouTubeTranscriptApi()

for vid in test_ids[:3]:
    title = [v['snippet']['title'][:40] for v in vresp['items'] if v['id'] == vid][0]
    try:
        # 먼저 가용 트랜스크립트 목록 확인
        tlist = api.list(vid)
        langs = [(t.language_code, t.is_generated) for t in tlist]
        print(f"\n  [{vid}] {title}")
        print(f"    가용 언어: {langs}")
        
        # 실제 fetch
        fetched = api.fetch(vid, languages=['ko', 'en'])
        text = '\n'.join(s.text for s in fetched)
        print(f"    트랜스크립트: {len(text):,}자 ✅")
        # 처음 200자만 미리보기
        preview = text[:200].replace('\n', ' ')
        print(f"    미리보기: {preview}...")
        
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable) as e:
        print(f"\n  [{vid}] {title}")
        print(f"    트랜스크립트 없음: {type(e).__name__}")
    except Exception as e:
        if IpBlocked and isinstance(e, IpBlocked):
            print(f"\n  [{vid}] {title}")
            print(f"    IpBlocked — VPN 필요")
        else:
            print(f"\n  [{vid}] {title}")
            print(f"    오류: {type(e).__name__}: {e}")
