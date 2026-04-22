---
name: yt-digest
description: >
  YouTube 채널의 영상을 트랜스크립트해서 지정 양식으로 정리해달라는 요청에 실행한다.
  트리거 예시: "유튜브 정리해줘", "이 채널 안본 영상 정리", "저번주 영상 분석해줘",
  "최신 영상 트랜스크립트해줘", "이 영상 정리해줘 [URL]", "[채널] 영상 [기간] 동안 정리"
  정리 모드: heavy(심층분석, 기본), medium(줄거리파악), compact(고밀도 압축)
  처리 엔진: claude(Claude Code 세션 직접, 기본) / gemini(Gemini API 자동 처리) / local(OpenAI 호환 로컬 LLM, 토큰 절약)
---

# 유튜브 정리하기 (yt-digest)

## 역할
특정 YouTube 채널의 영상을 트랜스크립트해서 `deep_analysis.md` 양식으로 정리하고
`output/{채널명}/` 폴더에 마크다운 파일로 저장한다.

---

## Step 0 — 요청 파악

사용자 요청에서 다음을 파악한다. 없는 항목은 질문한다.

| 항목 | 파악 방법 |
|------|-----------|
| **채널 URL** | 메시지에서 추출. 없으면 질문 |
| **조회 모드** | 아래 표 참고해서 판단 |
| **정리 모드** | 아래 표 참고해서 판단. 미지정 시 heavy 기본 |
| **처리 엔진** | "Gemini로"/"자동으로"→`--llm gemini`, "로컬로"/"Ollama로"/"토큰 아끼게"→`--llm local`, 기본은 `claude` |
| **기간** | 조회 모드에 따라 필요 시 질문 |
| **키워드** | 조회 모드 3일 때 추출 |

### 정리 모드 판단

| 사용자 표현 | 모드 | `--mode` |
|------------|------|---------|
| "심층 분석", "자세히", "원문 포함", 기본 | Heavy | `heavy` |
| "줄거리만", "간략히", "빠르게", "요약만" | Medium | `medium` |
| "한줄요약", "압축", "핵심만", "토큰 아껴서" | Compact | `compact` |

### 모드 판단 기준

| 사용자 표현 | 모드 | CLI 옵션 |
|------------|------|---------|
| "최신 영상", "가장 최근 안본 것" | 모드 1 | `--latest` |
| "~부터 ~까지", "이번 달", "저번 주" | 모드 2 | `--start` `--end` |
| "~키워드 있는 영상", "~관련 영상" | 모드 3 | `--keyword` |
| "전부", "다시 정리", "모든 영상" | 모드 4 | `--start` `--end` `--all` |
| 단일 URL 제공 | 단일 | `--url` |

기간 표현 변환 예시 (오늘: 실행 시점 날짜 기준):
- "이번 달" → `--start {이번달 1일}` `--end {오늘}`
- "저번 주" → `--start {저번주 월요일}` `--end {저번주 일요일}`
- "최근 한 달" → `--start {30일 전}` `--end {오늘}`

---

## Step 1 — 트랜스크립트 수집

파악한 모드에 맞춰 `main.py`를 실행한다.

```bash
# 단일 URL
python main.py --url "{영상URL}" --mode {heavy|medium|compact}

# 모드 1
python main.py --channel "{채널URL}" --latest --mode {heavy|medium|compact}

# 모드 2
python main.py --channel "{채널URL}" --start {YYYY-MM-DD} --end {YYYY-MM-DD} --mode {heavy|medium|compact}

# 모드 3
python main.py --channel "{채널URL}" --keyword "{키워드}" --mode {heavy|medium|compact}

# 모드 4
python main.py --channel "{채널URL}" --start {YYYY-MM-DD} --end {YYYY-MM-DD} --all --mode {heavy|medium|compact}

# Gemini 엔진으로 자동 처리 (pending.json 생성 후 바로 Gemini가 output까지 저장)
python main.py --url "{영상URL}" --mode {heavy|medium|compact} --llm gemini [--gemini-model {pro|thinking|flash}]
```

`--mode` 생략 시 `heavy`, `--llm` 생략 시 `claude` 기본 적용.
`--llm gemini` 는 `.env`에 `GEMINI_API_KEY` 필요. 티어 미지정 시 pro → thinking → flash 자동 폴백.

실행 후 `./cache/pending.json`을 읽어 처리 대상 목록을 확인한다.
`pending`이 비어 있으면 "처리할 새 영상이 없습니다"로 종료.

---

## Step 2 — 양식 정리 (LLM 처리)

**`--llm gemini`로 실행한 경우**: Step 1에서 `main.py`가 이미 output 파일 저장 + `mark_processed()` 호출까지 수행하므로 이 단계는 스킵하고 Step 3으로 이동한다.

**`--llm claude` (기본)**: 아래 절차를 수행한다. `pending` 목록의 각 항목에 대해 순서대로 처리한다.

각 영상마다:

1. `metadata_path` 경로의 JSON 파일을 읽어 메타데이터를 확인한다
   - 없으면 `pending.json`의 해당 항목에서 title, channel_name, published_at, url, duration을 사용한다
2. `transcript_path` 경로의 트랜스크립트 파일을 읽는다
3. 트랜스크립트에서 주요 출연진(발표자, MC, 기타 화자)을 파악한다
4. 분석 문서를 작성한다. **파일 최상단에 반드시 아래 메타데이터 헤더를 포함한다**:

```markdown
# {title}

**채널**: {channel_name}
**날짜**: {published_at}
**링크**: {url}
**길이**: {duration}
**출연진**: {트랜스크립트에서 파악한 주요 화자}

---
```

5. 이후 선택된 템플릿(`template` 필드) 양식을 적용해서 본문을 작성한다
6. 완성된 문서를 `output/{채널명}/{published_at}_{제목슬러그}.md`로 저장한다
7. `src/storage.py`의 `mark_processed(video_id, channel_dir)`를 호출한다

여러 영상이 있을 경우 한 영상씩 완료 후 다음으로 넘어간다.

---

## Step 3 — 결과 안내

처리가 완료되면 다음 형식으로 결과를 안내한다.

```
정리 완료: {N}개 영상
채널: {채널명}

저장된 파일:
- output/{채널명}/{날짜}_{제목}.md
- output/{채널명}/{날짜}_{제목}.md
...

트랜스크립트가 없어 스킵된 영상: {M}개 (있을 경우에만 표시)
```

---

## 주의사항

- `YOUTUBE_API_KEY`가 `.env`에 없으면 단일 URL 모드만 가능하다. 채널 모드 요청 시 API 키 설정을 안내한다.
- 트랜스크립트가 없는 영상(비공개 자막 등)은 스킵하고 로그에 기록한다.
- 이미 처리된 영상(`.processed.json`에 있는)은 모드 2에서 자동 스킵된다. `--all` 옵션으로 재처리 가능.
