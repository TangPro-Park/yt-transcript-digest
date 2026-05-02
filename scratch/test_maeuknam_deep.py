"""매억남 영상 1개 전체 트랜스크립트 + 타임스탬프 추출하여 구조 분석"""
import os, sys, json
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()

from youtube_transcript_api import YouTubeTranscriptApi
api = YouTubeTranscriptApi()

# 가장 긴 영상 (1시간 13분) — 분석할 내용이 많을 것
vid = 'ekAkELSZMi0'  # 2026.04.15 라이브

fetched = api.fetch(vid, languages=['ko'])

# 타임스탬프 포함 전체 저장
segments = []
for s in fetched:
    segments.append({
        'start': round(s.start, 1),
        'duration': round(s.duration, 1),
        'text': s.text,
    })

# 1. 타임스탬프별 원본 저장
with open('scratch/maeuknam_full_transcript.json', 'w', encoding='utf-8') as f:
    json.dump(segments, f, ensure_ascii=False, indent=2)

# 2. 읽기 편한 텍스트 버전 (시간 마커 포함)
with open('scratch/maeuknam_full_transcript.txt', 'w', encoding='utf-8') as f:
    current_minute = -1
    for s in segments:
        minute = int(s['start'] // 60)
        if minute != current_minute:
            current_minute = minute
            f.write(f"\n--- [{minute:02d}:{int(s['start'] % 60):02d}] ---\n")
        f.write(s['text'] + '\n')

# 3. 통계
total_chars = sum(len(s['text']) for s in segments)
total_secs = segments[-1]['start'] + segments[-1]['duration'] if segments else 0

print(f"Video: {vid}")
print(f"Segments: {len(segments)}")
print(f"Total chars: {total_chars:,}")
print(f"Duration: {int(total_secs//60)}m {int(total_secs%60)}s")
print(f"Saved: scratch/maeuknam_full_transcript.txt")
print(f"Saved: scratch/maeuknam_full_transcript.json")

# 4. 구간별 단어 밀도 분석 (5분 단위)
print(f"\n=== 5분 단위 내용 밀도 ===")
bucket_size = 300  # 5분
buckets = {}
for s in segments:
    b = int(s['start'] // bucket_size)
    if b not in buckets:
        buckets[b] = {'chars': 0, 'texts': []}
    buckets[b]['chars'] += len(s['text'])
    buckets[b]['texts'].append(s['text'])

for b in sorted(buckets.keys()):
    minute_start = b * 5
    chars = buckets[b]['chars']
    sample = ' '.join(buckets[b]['texts'][:3])[:80]
    print(f"  [{minute_start:3d}~{minute_start+5:3d}분] {chars:5,}자 | {sample}...")
