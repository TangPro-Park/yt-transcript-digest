"""elliott_wave 템플릿으로 실제 트랜스크립트 처리 테스트 (Gemini flash)"""
import os, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()

api_key = os.getenv('GEMINI_API_KEY')
if not api_key:
    print("GEMINI_API_KEY 필요")
    sys.exit(1)

from google import genai

# 1. 템플릿 읽기
with open('templates/elliott_wave.md', encoding='utf-8') as f:
    template = f.read()

# 2. 트랜스크립트 읽기
with open('scratch/maeuknam_full_transcript.txt', encoding='utf-8') as f:
    transcript = f.read()

# 3. 프롬프트 조합
prompt = f"""{template}

---

## 입력 트랜스크립트

**영상 제목**: [2026.04.15] 비트코인 분석과 실시간 Live 방송
**영상 URL**: https://www.youtube.com/watch?v=ekAkELSZMi0
**공개일**: 2026-04-15

{transcript}
"""

# 4. Gemini flash 호출
client = genai.Client(api_key=api_key)

print("Gemini flash 호출 중...")
response = client.models.generate_content(
    model='gemini-2.5-flash',
    contents=prompt,
)

result = response.text
print(f"응답 길이: {len(result):,}자")

# 5. 결과 저장
with open('scratch/maeuknam_elliott_test_result.md', 'w', encoding='utf-8') as f:
    f.write(result)

print("저장: scratch/maeuknam_elliott_test_result.md")
