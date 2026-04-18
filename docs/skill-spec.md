# 스킬 명세서 — yt-digest (유튜브 정리하기)

**버전**: 1.2.0
**작성일**: 2026-04-18 (Rev. compact 모드 + Gemini 엔진 반영)
**스킬 위치**: `.claude/skills/yt-digest/`

---

## 1. 개요

YouTube 영상의 트랜스크립트를 추출하고 선택한 정리 모드로 분석해 마크다운 파일로 저장하는 스킬.

- **처리 엔진 2종**:
  - `claude` (기본): Anthropic API 키 불필요. Claude Code 세션이 `pending.json`을 읽어 직접 LLM 역할 수행
  - `gemini` (`--llm gemini`): `GEMINI_API_KEY` 필요. `main.py`가 Gemini API로 end-to-end 자동 처리 (pro → thinking → flash 자동 폴백)
- YouTube Data API 키는 채널 모드에서만 필요. 단일 URL 모드는 oembed로 title/채널명만 조회 (키 없이 동작)

---

## 2. 정리 모드

| 모드 | 이름 | 템플릿 | 특징 |
|------|------|--------|------|
| `heavy` | 심층 분석 (기본) | `templates/deep_analysis.md` | 원문 전체 포함 + 소주제별 심층 해설 + 프리뷰/끝인사/전체 요약 |
| `medium` | 줄거리 파악 | `templates/medium_summary.md` | 원문 생략, 핵심 해설만. 빠른 내용 파악용 |
| `compact` | 고밀도 압축 | `templates/compact.md` | 원문 생략, 핵심 주장/키워드 중심 고밀도 압축. 토큰 절약용 |

세 모드 모두 스크립트 길이 기반 **동적 비례 배분**(5구간: 10분/30분/50분/70분/70분+)을 적용해 분량에 맞게 구조/서술량을 자동 조절한다.

### Heavy 모드 출력 구조

```
[프리뷰]       ← 도입부 원문 포함
[본문]         ← 대주제별 심층 해설 + 해당 구간 원문
[전체 요약]    ← A4 2페이지 분량
[끝인사]       ← 마무리 원문 포함
```

### Medium 모드 출력 구조

```
[한눈에 보기]  ← 배경/전개/결론 3단 요약
[본문]         ← 대주제 2~5개, 소주제별 핵심 해설만
               (원문·프리뷰·끝인사 생략)
[최종 결론]    ← 전체 요약
```

### Compact 모드 출력 구조

```
[한눈에 보기]    ← 3단 흐름 요약 (2~10줄)
[핵심 주장]      ← 1~5개 (길이 비례), 맥락+예시+시사점
[키워드 & 개념]  ← 주요 용어 심층 해설
[최종 시사점]    ← 2~3줄 결론
```

---

## 3. 사전 준비

### 3-1. 의존성 설치

```bash
pip install -r requirements.txt
```

```
google-api-python-client
youtube-transcript-api
python-dotenv
pyyaml
google-generativeai          # --llm gemini 경로용
```

### 3-2. 환경 변수

`.env` 파일 생성:

```
YOUTUBE_API_KEY=your_youtube_data_api_v3_key_here   # 채널 모드 필요
GEMINI_API_KEY=your_gemini_api_key_here             # --llm gemini 경로 필요
```

- **YouTube Data API v3 키**: Google Cloud Console → API 및 서비스 → YouTube Data API v3 사용 설정 (무료, 10,000 units/일)
- **Gemini API 키**: https://aistudio.google.com/apikey 에서 발급. 무료 티어 — pro: 일 25회 / thinking(2.5 flash): 일 500회 / flash(2.0): 일 1,500회

---

## 4. 기능 명세

### 4-1. 단일 URL 정리 ★ 메인

| 항목 | 내용 |
|------|------|
| 트리거 | "이 영상 정리해줘 [URL]", URL만 붙여넣기 |
| API 키 | 불필요 (Gemini 경로는 `GEMINI_API_KEY` 필요) |
| 동작 | URL → oembed로 채널/제목 조회 → 트랜스크립트 추출 → 정리 모드 적용 → .md 저장 |
| 출력 | `output/{채널명}/unknown-date_{제목}.md` (oembed 성공 시) |
| API 키 있을 때 | 실제 업로드 날짜 포함, `output/{채널명}/{YYYY-MM-DD}_{제목}.md` 에 저장 |

### 4-2. 최신 미처리 영상 (조회 모드 1)

| 항목 | 내용 |
|------|------|
| 트리거 | "최신 영상 정리해줘", "가장 최근 안본 영상 정리해줘" |
| API 키 | 필요 |
| 동작 | 채널 최신 업로드 순으로 순회 → `.processed.json`에 없는 첫 번째 영상 1개 처리 |
| 탐색 범위 | 최근 30개 영상 이내 |

### 4-3. 기간 내 미처리 영상 (조회 모드 2)

| 항목 | 내용 |
|------|------|
| 트리거 | "저번 달 영상 정리해줘", "1월부터 3월 영상 정리해줘" |
| API 키 | 필요 |
| 동작 | 지정 기간 영상 목록 수집 → 이미 처리된 영상 제외 → 나머지 일괄 처리 |
| 기간 미지정 시 | Claude가 자연어 해석 (이번 달, 저번 주 등) |

### 4-4. 키워드 검색 (조회 모드 3)

| 항목 | 내용 |
|------|------|
| 트리거 | "[키워드] 관련 영상 정리해줘", "[키워드] 영상 찾아서 정리해줘" |
| API 키 | 필요 (search API, 100 quota units/call) |
| 동작 | 채널 내 키워드 검색 → 결과 영상 일괄 처리 |
| 기간 조합 | `--start` / `--end` 옵션으로 범위 제한 가능 |

### 4-5. 기간 내 전체 재처리 (조회 모드 4)

| 항목 | 내용 |
|------|------|
| 트리거 | "이 기간 영상 전부 다시 정리해줘", "모든 영상 정리해줘" |
| API 키 | 필요 |
| 동작 | 기간 내 전체 영상 처리 (이미 처리된 것도 포함) |
| 주의 | 기존 파일 덮어씀 |

---

## 5. 출력 명세

### 5-1. 파일 경로

```
output/
└── {채널명}/
    ├── .processed.json          # 처리 완료 video_id 목록 (숨김)
    ├── INDEX.md                 # 전체 목록
    └── {YYYY-MM-DD}_{제목}.md  # 분석 결과
```

### 5-2. 캐시

```
cache/
├── transcripts/{video_id}.txt  # 원본 트랜스크립트 (재사용)
└── pending.json                # 현재 처리 대기 목록 (mode 필드 포함)
```

---

## 6. 사용 방법

### 6-1. 스킬 (자연어)

```
# Heavy (기본) — 심층 분석
이 영상 정리해줘 https://youtu.be/xxxx
이 채널 최신 안본 영상 정리해줘 https://youtube.com/@handle

# Medium — 줄거리만 빠르게
이 영상 줄거리만 정리해줘 https://youtu.be/xxxx
저번 달 영상 간략히 정리해줘 https://youtube.com/@handle
```

### 6-2. CLI 직접 실행

```bash
# 단일 URL — Heavy (기본, Claude 경로)
python main.py --url "https://youtu.be/xxxx"

# 단일 URL — Medium / Compact
python main.py --url "https://youtu.be/xxxx" --mode medium
python main.py --url "https://youtu.be/xxxx" --mode compact

# Gemini 자동 처리 (.env에 GEMINI_API_KEY 필요)
python main.py --url "https://youtu.be/xxxx" --llm gemini
python main.py --url "https://youtu.be/xxxx" --llm gemini --gemini-model flash

# Gemini 티어 안내
python main.py --gemini-info

# 조회 모드 1 — Medium
python main.py --channel "https://youtube.com/@handle" --latest --mode medium

# 조회 모드 2 — Heavy + Gemini
python main.py --channel "https://youtube.com/@handle" --start 2026-01-01 --end 2026-04-18 --llm gemini

# 조회 모드 3 — Compact
python main.py --channel "https://youtube.com/@handle" --keyword "클로드" --mode compact

# 조회 모드 4 — 전체 재처리
python main.py --channel "https://youtube.com/@handle" --start 2026-01-01 --end 2026-04-18 --all
```

---

## 7. 제약 및 주의사항

| 항목 | 내용 |
|------|------|
| 트랜스크립트 없는 영상 | 자동 스킵, 로그에 기록 |
| 비공개/멤버십 영상 | 트랜스크립트 접근 불가, 스킵 |
| YouTube API 할당량 | 10,000 units/일. 키워드 검색은 100 units/call로 소모 빠름 |
| 영상 최대 처리 수 | `config.yaml`의 `max_videos` 기본값 50 |
| 언어 우선순위 | `ko` → `en` → 가용 언어 순 fallback |

---

## 8. 다른 프로젝트 이식

### 방법 A — 파일 복사

아래 파일을 대상 프로젝트 루트에 복사:

```
main.py
src/
templates/
requirements.txt
.env
.claude/skills/yt-digest/
```

### 방법 B — 플러그인 ZIP

```
Claude Code에서: "yt-digest 플러그인 ZIP으로 패키징해줘"
대상 프로젝트에서: /plugin → Personal → Upload Plugin
```
