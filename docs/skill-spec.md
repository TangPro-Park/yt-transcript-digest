# 스킬 명세서 — yt-digest (유튜브 정리하기)

**버전**: 2.0.0
**작성일**: 2026-04-28 (Rev. Fetch Run/Registry 아키텍처 + 인기순/통계스캔 반영)
**스킬 위치**: `.claude/skills/yt-digest/`

---

## 1. 개요

YouTube 영상의 트랜스크립트를 추출하고 선택한 정리 모드로 분석해 마크다운 파일로 저장하는 스킬.

- **처리 엔진 3종**:
  - `claude` (기본): Anthropic API 키 불필요. Claude Code subprocess가 `--tools ""` + `--system-prompt`로 텍스트 생성기 모드로 작동
  - `gemini` (`--llm gemini`): `GEMINI_API_KEY` 필요. pro → thinking → flash 자동 폴백
  - `local` (`--llm local`): OpenAI 호환 로컬 LLM (Ollama, LM Studio 등). `config.yaml`의 `local_llm` 섹션
- YouTube Data API 키는 채널 모드에서만 필요. 단일 URL 모드는 oembed로 title/채널명만 조회 (키 없이 동작)

---

## 2. 정리 모드

| 모드 | 이름 | 템플릿 | 특징 |
|------|------|--------|------|
| `heavy` | 심층 분석 (기본) | `templates/deep_analysis.md` | 원문 전체 포함 + 소주제별 심층 해설 + 프리뷰/끝인사/전체 요약 |
| `medium` | 줄거리 파악 | `templates/medium_summary.md` | 원문 생략, 핵심 해설만. 빠른 내용 파악용 |
| `compact` | 고밀도 압축 | `templates/compact.md` | 원문 생략, 핵심 주장/키워드 중심 고밀도 압축. 토큰 절약용 |
| `compact_local` | 로컬 전용 압축 | `templates/compact_local.md` | compact와 유사하나 분량 파라미터를 사전 계산해 주입 |
| `shorts` | 쇼츠 전문 | `templates/shorts.md` | 화자분리 전문. 쇼츠/짧은 영상 전용 |

세 모드 모두 스크립트 길이 기반 **동적 비례 배분**(5구간: 10분/30분/50분/70분/70분+)을 적용해 분량에 맞게 구조/서술량을 자동 조절한다.

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
google-genai          # --llm gemini 경로용
openai                # --llm local 경로용
requests              # IpBlocked v0 폴백용
```

### 3-2. 환경 변수

`.env` 파일 생성:

```
YOUTUBE_API_KEY=your_youtube_data_api_v3_key_here   # 채널 모드 필요
GEMINI_API_KEY=your_gemini_api_key_here             # --llm gemini 경로 필요
```

---

## 4. 기능 명세

### 4-1. 단일 URL 정리 ★ 메인

| 항목 | 내용 |
|------|------|
| 트리거 | "이 영상 정리해줘 [URL]", URL만 붙여넣기 |
| API 키 | 불필요 (Gemini 경로는 `GEMINI_API_KEY` 필요) |
| 동작 | URL → oembed로 채널/제목 조회 → 트랜스크립트 추출 → 정리 모드 적용 → .md 저장 |
| 출력 | `output/{채널명}/unknown-date_{제목}.md` (oembed 성공 시) |
| API 키 있을 때 | 실제 업로드 날짜 포함, `output/{채널명}/{YYYY-MM-DD}_{제목}.md` |

### 4-2. 최신 미처리 영상 (조회 모드 1)

| 항목 | 내용 |
|------|------|
| 트리거 | "최신 영상 정리해줘", `--latest [N]` |
| API 키 | 필요 |
| 동작 | 채널 최신 업로드 순으로 순회 → `.processed.json`에 없는 영상 N개 처리 |
| N 미지정 | 1개 (기존 동작 유지) |
| 탐색 범위 | 최근 30개 영상 이내 |

### 4-3. 기간 내 미처리 영상 (조회 모드 2)

| 항목 | 내용 |
|------|------|
| 트리거 | "저번 달 영상 정리해줘", "1월부터 3월 영상 정리해줘" |
| API 키 | 필요 |
| 동작 | 지정 기간 영상 목록 수집 → 이미 처리된 영상 제외 → 나머지 일괄 처리 |

### 4-4. 키워드 검색 (조회 모드 3)

| 항목 | 내용 |
|------|------|
| 트리거 | "[키워드] 관련 영상 정리해줘" |
| API 키 | 필요 (search API, 100 quota units/call) |
| 동작 | 채널 내 키워드 검색 → 결과 영상 일괄 처리 |
| 기간 조합 | `--start` / `--end` 옵션으로 범위 제한 가능 |

### 4-5. 인기순 영상 (조회 모드 5) ★ 신규

| 항목 | 내용 |
|------|------|
| 트리거 | `--popular` 또는 `--popular-scan` |
| API 키 | 필요 |
| `--popular` | search.list 기반 (빠름, 쇼츠 포함 가능) |
| `--popular-scan` | statistics 기반 (정확한 조회수 정렬 + 쇼츠 자동 필터) |
| 출력 | `output/{채널명}/인기/` 서브디렉터리 + POPULAR.md 인덱스 |
| 상위 N개 | `--top N` (기본 50) |

### 4-6. 분리 실행 (Fetch / Digest)

| 항목 | 내용 |
|------|------|
| `--fetch-only` | 트랜스크립트만 수집 + pending.json 저장 (LLM 처리 스킵) |
| `--digest-only` | pending.json 읽어 LLM 처리만 실행 |
| `--digest-from-registry` | fetch run의 video_ids 순서로 계획 수립 → digest |
| `--from-run` | 대상 run: `latest`(기본) 또는 명시적 run_id |
| `--from-run-kind` | popular/range/keyword/latest/single 중 최신 run 선택 |

### 4-7. Claude 모델 선택

| 모델 | 플래그 | 특징 |
|------|--------|------|
| haiku (기본) | `--claude-model haiku` | 빠름, 저비용 |
| sonnet | `--claude-model sonnet` | 균형 |
| opus | `--claude-model opus` | 최고 품질 |

### 4-8. 키워드 필터링

`config.yaml`의 `filter.skip_keywords`에 키워드를 등록하면, 제목에 해당 키워드가 포함된 영상은 자동 스킵된다. 대소문자 구분 없음.

---

## 5. 출력 명세

### 5-1. 파일 경로

```
output/
└── {카테고리}/
    └── {채널명}/
        ├── .processed.json          # 처리 완료 video_id 목록 (숨김)
        ├── INDEX.md                 # 전체 목록
        ├── POPULAR.md               # 인기 영상 인덱스
        ├── 인기/                    # --popular 결과
        │   └── {YYYY-MM-DD}_{제목}.md
        └── {YYYY-MM-DD}_{제목}.md   # 기본 경로
```

### 5-2. 캐시

```
cache/
├── transcripts/               # {video_id}.txt + {video_id}.json (메타데이터)
├── transcripts.json           # 전체 fetch 레지스트리 + digest 이력 (영속)
├── fetch_runs.json            # fetch 실행 단위 묶음 (영속)
├── pending.json               # 현재 처리 대기 목록 (1회용, 완료 시 archived)
└── digested/                  # 완료된 pending 아카이브 (영속)
    └── {timestamp}.json
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

# 인기 영상 분석
이 채널 인기 영상 TOP 20 정리해줘 https://youtube.com/@handle
```

### 6-2. CLI 직접 실행

```bash
# 단일 URL
python main.py --url "https://youtu.be/xxxx"
python main.py --url "https://youtu.be/xxxx" --mode medium
python main.py --url "https://youtu.be/xxxx" --llm gemini --gemini-model flash

# 최신 미처리
python main.py --channel URL --latest          # 1개
python main.py --channel URL --latest 5        # 5개

# 기간 조회
python main.py --channel URL --start 2026-01-01 --end 2026-04-30

# 인기순
python main.py --channel URL --popular --top 50
python main.py --channel URL --popular-scan --top 50     # 정확 조회수 + 쇼츠 필터

# 분리 실행
python main.py --channel URL --popular --top 100 --fetch-only
python main.py --digest-from-registry --from-run-kind popular --top 20 --mode heavy --claude-model haiku

# Gemini 티어 안내
python main.py --gemini-info
```

---

## 7. Fetch Run 시스템 (v2.0 신규)

### 개념
모든 fetch 실행은 `run_id`(타임스탬프)로 묶이며, registry에 영상별 상태가 기록된다.

### 워크플로우
```
[Fetch] --fetch-only        →  fetch_runs.json + transcripts.json 업데이트
[Plan]  --digest-from-registry  →  registry에서 pending.json 자동 생성
[Digest] LLM 처리           →  output/ 저장 + registry 업데이트
[Archive] 완료              →  pending → cache/digested/ 이동
```

### 활용 예시
```bash
# 1. 인기 TOP 100을 먼저 수집만
python main.py --channel URL --popular --top 100 --fetch-only

# 2. 그 중 상위 20개만 heavy로 처리
python main.py --digest-from-registry --from-run-kind popular --top 20 --mode heavy

# 3. 나머지 80개는 compact로 처리
python main.py --digest-from-registry --from-run-kind popular --mode compact
```

---

## 8. 제약 및 주의사항

| 항목 | 내용 |
|------|------|
| 트랜스크립트 없는 영상 | 자동 스킵, 로그에 기록 |
| 비공개/멤버십 영상 | 트랜스크립트 접근 불가, 스킵 |
| YouTube API 할당량 | 10,000 units/일. 키워드 검색은 100 units/call |
| 영상 최대 처리 수 | `config.yaml`의 `max_videos` 기본값 50 |
| 언어 우선순위 | `ko` → `en` → 가용 언어 순 fallback |
| IpBlocked | v0 폴백 자동 시도 (innertube 우회) |
| Claude CLI 에이전트 오염 | `--tools ""` + `--system-prompt`로 차단됨 |
