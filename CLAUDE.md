# YouTube Transcript Digest

## 프로젝트 목적
특정 YouTube 채널의 영상 **트랜스크립트(전사본)**를 추출하고,
LLM으로 원하는 양식에 맞게 정리하여 마크다운 파일로 저장하는 파이프라인.

## 핵심 설계 결정

### 트랜스크립트 추출 방식
- YouTube가 자체 제공하는 트랜스크립트를 직접 가져옴 (자막과 다름)
- `youtube-transcript-api` Python 라이브러리 사용 (무료, 오디오 다운로드 불필요)
- 언어 우선순위: `['ko', 'en']` → 가용 언어 자동 폴백
- IpBlocked 시 innertube 우회 (v0 폴백: 직접 페이지 파싱 + timedtext XML)
- 트랜스크립트 없는 영상은 스킵 + 로그 기록

### LLM 처리 방식 — 3가지 경로
| 경로 | 엔진 | 플래그 | 특징 |
|------|------|--------|------|
| **Claude CLI** (기본) | Claude Code subprocess | `--llm claude` | `--tools ""` + `--system-prompt`로 에이전트 모드 차단. API 키 불필요 |
| **Gemini API** | Google Gemini | `--llm gemini` | pro → thinking → flash 자동 폴백. `GEMINI_API_KEY` 필요 |
| **Local LLM** | OpenAI 호환 (Ollama 등) | `--llm local` | `config.yaml`의 `local_llm` 섹션. `compact_local` 모드 전용 템플릿 |

### 파이프라인 흐름
```
[1] YouTube Data API v3  (discover.py)
    channels.list / playlistItems / search
    → 영상 메타데이터 목록 + 확장 메타데이터 (chapters, tags, statistics)

[2] youtube-transcript-api  (transcript.py)
    각 video_id → 트랜스크립트 텍스트
    → cache/transcripts/{video_id}.txt + {video_id}.json 저장

[3] Fetch Run 기록  (fetch_runs.py + registry.py)
    fetch 실행 단위(run_id) 묶음 → cache/fetch_runs.json
    영상별 상태 추적 (queued → fetched → digested) → cache/transcripts.json

[4] Digest 계획 수립  (plan.py)
    registry + fetch_runs 데이터로 pending.json 작성
    순서 보존, 중복 방지, skip_already 로직

[5] LLM 처리  (claude_cli.py / llm.py / llm_processor.py)
    pending.json 읽기 → 템플릿 적용 → 마크다운 생성
    → output/{채널명}/{subdir}/{YYYY-MM-DD}_{제목}.md

[6] 아카이브  (digest_archive.py)
    완료된 pending.json → cache/digested/{timestamp}.json

[7] 인덱스 생성
    INDEX.md, POPULAR.md 자동 생성
```

## 정리 모드
| 모드 | 플래그 | 템플릿 | 용도 |
|------|--------|--------|------|
| `heavy` (기본) | `--mode heavy` | `deep_analysis.md` | 원문 전체 + 심층 해설 |
| `medium` | `--mode medium` | `medium_summary.md` | 원문 생략, 핵심 해설만 |
| `compact` | `--mode compact` | `compact.md` | 고밀도 압축 요약 |
| `compact_local` | `--mode compact_local` | `compact_local.md` | 로컬 LLM 전용 (파라미터 사전 계산) |
| `shorts` | `--mode shorts` | `shorts.md` | 쇼츠 전용 화자분리 전문 |

## 프로젝트 구조
```
yt-transcript-digest/
├── CLAUDE.md                  # 이 파일
├── config.yaml                # 채널, 기간, LLM, 필터 설정
├── .env                       # API 키 (gitignore)
├── .env.example
├── requirements.txt
├── main.py                    # CLI 진입점 + 파이프라인 오케스트레이터
├── src/
│   ├── __init__.py
│   ├── constants.py           # TEMPLATES dict 등 전역 상수 (단일 원본)
│   ├── discover.py            # YouTube Data API → 영상 목록 (latest/range/keyword/popular)
│   ├── transcript.py          # 트랜스크립트 추출 + 캐시 (v1 + v0 폴백)
│   ├── storage.py             # 파일 저장, INDEX.md, .processed.json
│   ├── registry.py            # 영상별 생애주기 추적 (영속 원장, cache/transcripts.json)
│   ├── fetch_runs.py          # fetch 실행 단위 묶음 (cache/fetch_runs.json)
│   ├── plan.py                # registry + fetch_runs → pending.json 계획 수립
│   ├── digest_runner.py       # --digest-only / --digest-from-registry 실행기 (DI 기반)
│   ├── digest_archive.py      # 완료된 pending → cache/digested/ 아카이브
│   ├── claude_cli.py          # Claude CLI subprocess 호출 (--tools "" 에이전트 차단)
│   ├── llm.py                 # Gemini API 호출 + 프롬프트 빌더
│   ├── llm_processor.py       # 로컬 LLM (OpenAI 호환) 처리기
│   └── prompt_params.py       # 로컬 LLM용 동적 분량 파라미터 계산기
├── templates/
│   ├── deep_analysis.md       # heavy 모드 (심층 분석)
│   ├── medium_summary.md      # medium 모드 (줄거리 파악)
│   ├── compact.md             # compact 모드 (고밀도 압축)
│   ├── compact_local.md       # compact_local 모드 (로컬 LLM 전용)
│   ├── shorts.md              # shorts 모드 (쇼츠 전용)
│   └── default.md             # 기본 양식 (미사용)
├── cache/
│   ├── transcripts/           # {video_id}.txt + {video_id}.json
│   ├── transcripts.json       # 전체 fetch 레지스트리 + digest 이력 (영속)
│   ├── fetch_runs.json        # fetch 실행 단위 묶음 (영속)
│   ├── pending.json           # 현재 digest 계획 (1회용, 완료 시 archived)
│   └── digested/              # 완료된 pending 아카이브 (영속)
├── output/                    # 최종 마크다운 결과물
│   └── {카테고리}/{채널명}/
│       ├── INDEX.md
│       ├── POPULAR.md
│       └── 인기/              # --popular run 결과
├── docs/
│   ├── skill-spec.md          # 스킬 명세서
│   ├── workflow-unified.md    # 통합 워크플로우
│   ├── workflow-fetch.md      # Fetch 단계 상세
│   ├── workflow-digest.md     # Digest 단계 상세
│   └── devlog/                # 세션별 개발 로그
└── logs/                      # 실행 로그
```

## 필요한 API 키
- `YOUTUBE_API_KEY` : YouTube Data API v3 (Google Cloud Console, 무료 10,000 units/일). 채널 모드 필요
- `GEMINI_API_KEY` : Gemini API (aistudio.google.com/apikey). `--llm gemini` 경로만 필요
- Anthropic API 키 불필요 (`--llm claude` 경로는 Claude Code 세션 직접 활용)

## 의존성
```
google-api-python-client
youtube-transcript-api
python-dotenv
pyyaml
google-genai          # --llm gemini 경로
openai                # --llm local 경로
requests              # IpBlocked v0 폴백
```

## config.yaml 구조
```yaml
youtube:
  channel_url: ""           # 대상 채널 URL (CLI --channel이 우선)
  date_range:
    start: ""               # YYYY-MM-DD
    end: ""
  languages: ["ko", "en"]
  max_videos: 50

output:
  base_dir: "./output/취미/위스키"

local_llm:                   # --llm local 사용 시
  base_url: "http://localhost:11434/v1"
  model: "qwen3.5:9b"
  temperature: 0.1
  max_tokens: 4096
  num_ctx: 8192

speakers:                    # 프롬프트 치환용 (선택)
  main_speaker: ""
  mc: ""
  other_speaker: ""

filter:                      # 키워드 필터링 (제목 기반 자동 스킵)
  skip_keywords: ["백주", "고량주", "바이주"]
```

## 주요 CLI 명령
```bash
# 단일 URL
python main.py --url "https://youtu.be/xxxx" --mode heavy
python main.py --url "https://youtu.be/xxxx" --llm gemini

# 최신 미처리 영상
python main.py --channel URL --latest         # 1개
python main.py --channel URL --latest 5       # 5개

# 기간 조회
python main.py --channel URL --start 2026-01-01 --end 2026-04-30

# 인기순
python main.py --channel URL --popular --top 50         # search.list 방식
python main.py --channel URL --popular-scan --top 50    # 통계 기반 (쇼츠 필터)

# 분리 실행 (Fetch + Digest)
python main.py --channel URL --popular --top 100 --fetch-only
python main.py --digest-from-registry --from-run-kind popular --top 20 --mode heavy

# pending.json 직접 재사용
python main.py --digest-only --mode compact
```

## 추가 작업 규약 (에이전트 필독)

이 프로젝트는 **완성되어 운영 중인 상태**다. 새 기능 요청은 거의 항상 **"기존 동작을 건드리지 않고 추가"**를 의미한다. 대규모 리팩토링·재작성으로 오해하지 마라.

### 기본 규칙
- **기존 파일 수정 금지.** 새 기능은 **새 파일**에 작성하고, 기존 파일에는 `import` + dispatch 한두 줄만 추가한다.
- 사용자가 수정 가능 파일 화이트리스트를 주지 않았으면, **기존 파일은 읽기만** 하고 플랜을 먼저 제시해서 승인을 받는다.
- 기존 CLI 인자, 함수 시그니처, 파일 경로, 캐시 구조, `.processed.json` 스킴은 **불변**이다. 확장(choices에 항목 추가 등)은 허용, 변경은 금지.
- **TEMPLATES dict는 `src/constants.py`에서만 관리.** 모드 추가 시 이 파일만 수정.
- "개선"·"정리"·"더 나은 구조"는 **요청 범위 밖이다.** 요청된 것만 한다.

### 다중 파일 수정이 필요한 경우
1. plan mode로 먼저 구체적인 파일별 diff 계획을 제시
2. 사용자 승인 후에만 실행
3. 실행 중 범위가 커질 것 같으면 멈추고 재확인

### 복구 좌표
- `working-pre-local-llm` 태그 = 로컬 LLM 추가 직전의 "잘 돌던" 상태
- 사고 시: `git reset --hard working-pre-local-llm`
