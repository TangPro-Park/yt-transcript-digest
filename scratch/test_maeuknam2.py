"""매억남 라이브 다시보기 트랜스크립트 실제 내용 확인"""
import os, sys, json
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()

api_key = os.getenv('YOUTUBE_API_KEY')
from youtube_transcript_api import YouTubeTranscriptApi

api = YouTubeTranscriptApi()

# 가장 최근 라이브 다시보기
test_ids = ['R545_-W3wpI', 'ekAkELSZMi0', 'ml6fhGYRJPg']

results = []
for vid in test_ids:
    try:
        tlist = api.list(vid)
        langs = [(t.language_code, 'auto' if t.is_generated else 'manual') for t in tlist]
        
        fetched = api.fetch(vid, languages=['ko', 'en'])
        text = '\n'.join(s.text for s in fetched)
        
        results.append({
            'video_id': vid,
            'languages': langs,
            'char_count': len(text),
            'word_count': len(text.split()),
            'preview_200': text[:200],
            'preview_last_200': text[-200:],
            'status': 'OK'
        })
    except Exception as e:
        results.append({
            'video_id': vid,
            'status': f'ERROR: {type(e).__name__}: {e}'
        })

# JSON으로 저장
with open('scratch/maeuknam_test_result.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print("Done - scratch/maeuknam_test_result.json")
