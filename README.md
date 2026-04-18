# yt-transcript-digest

YouTube 영상의 트랜스크립트를 추출해 LLM으로 정리하는 파이프라인. **3단계 정리 모드**(심층/줄거리/압축) + **2종 LLM 엔진**(Claude Code / Gemini API) 지원.

## 특징

- **Anthropic API 키 불필요** — Claude Code 세션이 직접 LLM 역할 수행 (기본 경로)
- **Gemini API 자동 처리** — `--llm gemini`로 end-to-end 완전 자동화 (Pro→Thinking→Flash 자동 폴백)
- **3단계 정리 모드** — Heavy(원문 100% 포함) / Medium(해설만) / Compact(고밀도 압축)
- **동적 비례 배분** — 스크립트 길이에 맞춰 구조·서술량 자동 조절
- **5가지 조회 모드** — 단일 URL / 최신 미처리 / 기간 / 키워드 / 전체 재처리

## 설치

```bash
git clone <repo-url>
cd yt-transcript-digest
pip install -r requirements.txt
cp .env.example .env   # 키 채우기
```

### 환경 변수 (`.env`)

```
YOUTUBE_API_KEY=...   # 채널 모드에서만 필요 (Google Cloud Console)
GEMINI_API_KEY=...    # --llm gemini 경로 필요 (https://aistudio.google.com/apikey)
```

## 사용법

```bash
# 단일 URL — Claude 경로 (API 키 불필요)
python main.py --url "https://youtu.be/xxxx"

# 정리 모드 선택
python main.py --url "..." --mode heavy     # 심층 분석 (기본)
python main.py --url "..." --mode medium    # 줄거리 파악
python main.py --url "..." --mode compact   # 고밀도 압축

# Gemini 자동 처리
python main.py --url "..." --llm gemini
python main.py --url "..." --llm gemini --gemini-model flash

# 채널 모드 (YOUTUBE_API_KEY 필요)
python main.py --channel "https://youtube.com/@handle" --latest
python main.py --channel "..." --start 2026-01-01 --end 2026-04-18
python main.py --channel "..." --keyword "클로드"

# Gemini 티어 안내
python main.py --gemini-info
```

## Claude Code 스킬로 사용

`.claude/skills/yt-digest/` 디렉토리를 글로벌 위치로 복사하면 모든 프로젝트에서 사용 가능:

```bash
# Windows
cp -r .claude/skills/yt-digest "$USERPROFILE/.claude/skills/"

# macOS/Linux
cp -r .claude/skills/yt-digest ~/.claude/skills/
```

등록 후 자연어로 트리거:
- "이 영상 정리해줘 [URL]"
- "최신 영상 정리해줘"
- "저번 주 영상 간략히 정리해줘"

## 출력 구조

```
output/{채널명}/
├── .processed.json          # 처리 완료 video_id (중복 방지)
├── INDEX.md                 # 전체 목록
└── {YYYY-MM-DD}_{제목}.md   # 분석 결과
```

## 문서

- [스킬 명세서](docs/skill-spec.md)
- [토큰 사용량 명세](docs/token-spec.md)
- [개발 로그](docs/devlog-2026-04-18.md)

## 라이선스

MIT
