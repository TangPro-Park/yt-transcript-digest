# YouTube Transcript Digest

## 프로젝트 목적
특정 YouTube 채널의 기간 내 영상들의 **트랜스크립트(전사본)**를 추출하고,
LLM(Claude)으로 원하는 양식에 맞게 정리하여 마크다운 파일로 저장하는 파이프라인.

## 핵심 설계 결정

### 트랜스크립트 추출 방식
- YouTube가 자체 제공하는 트랜스크립트를 직접 가져옴 (자막과 다름)
- `youtube-transcript-api` Python 라이브러리 사용 (무료, 오디오 다운로드 불필요)
- 언어 우선순위: `['ko', 'en']`
- 트랜스크립트 없는 영상은 스킵 + 로그 기록

### LLM 처리 방식
- Claude API 호출 대신 **Claude Code 서브에이전트 직접 활용**
- `fetch.py`로 트랜스크립트 raw 텍스트 파일 저장 → Claude가 직접 읽고 포맷 변환
- API 키 별도 관리 불필요, Claude Code 세션 내에서 처리

### 파이프라인 흐름
```
[1] YouTube Data API v3
    channels.list → uploads playlist → playlistItems.list (기간 필터)
    → 영상 메타데이터 목록 (video_id, title, published_at, duration)

[2] youtube-transcript-api
    각 video_id → 트랜스크립트 텍스트
    → cache/transcripts/{video_id}.txt 저장

[3] Claude (서브에이전트)
    각 .txt 파일 읽기 + templates/deep_analysis.md 양식 적용
    → output/{channel_name}/{YYYY-MM-DD}_{title}.md 저장

[4] INDEX.md 자동 생성
    output/{channel_name}/INDEX.md
```

## 프로젝트 구조
```
yt-transcript-digest/
├── CLAUDE.md                  # 이 파일
├── config.yaml                # 채널, 기간, 설정
├── .env                       # API 키 (gitignore)
├── .env.example
├── requirements.txt
├── main.py                    # 파이프라인 오케스트레이터
├── src/
│   ├── discover.py            # YouTube Data API로 영상 목록
│   ├── transcript.py          # 트랜스크립트 추출
│   └── storage.py             # 파일 저장 및 인덱스 생성
├── templates/
│   └── deep_analysis.md      # 마크다운 양식 템플릿 (해설 포함)
├── cache/
│   └── transcripts/           # 추출된 원본 트랜스크립트
├── output/                    # 최종 마크다운 결과물
└── logs/                      # 실행 로그
```

## 필요한 API 키
- `YOUTUBE_API_KEY` : YouTube Data API v3 (Google Cloud Console, 무료 할당량 10,000 units/일)
- Anthropic API 키 불필요 (Claude Code 세션 직접 활용)

## 의존성
```
google-api-python-client
youtube-transcript-api
python-dotenv
```

## config.yaml 구조
```yaml
youtube:
  channel_url: ""         # 대상 채널 URL
  date_range:
    start: ""             # YYYY-MM-DD
    end: ""               # YYYY-MM-DD
  languages: ["ko", "en"]
  max_videos: 50

output:
  base_dir: "./output"
  filename_pattern: "{date}_{title_slug}.md"

resume: true              # 중단 후 재개 지원
```

## 마크다운 양식
`templates/deep_analysis.md` 참조. 사용자가 원하는 양식으로 자유롭게 수정 가능.

## 다음 작업
- [ ] config.yaml에 대상 채널 및 기간 입력
- [ ] .env에 YOUTUBE_API_KEY 입력
- [x] templates/deep_analysis.md 양식 확정
- [ ] `main.py` 구현 시작
