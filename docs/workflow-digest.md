# Digest 워크플로우

Fetch된 트랜스크립트를 LLM으로 처리해 마크다운 파일로 저장한다.

---

## 진입점 3가지

### 1. 레지스트리 기반 (권장)
```bash
python main.py --digest-from-registry \
  [--from-run latest | --from-run RUN_ID] \
  [--from-run-kind popular|range|keyword|latest|single] \
  [--top N] \
  --mode heavy \
  --llm claude --claude-model haiku
```
`plan.py`가 fetch run의 `video_ids` 순서 그대로 `pending.json`을 작성한 후 digest 실행.

### 2. pending.json 직접 사용
```bash
python main.py --digest-only [--mode compact]
```
현재 `cache/pending.json`을 읽어 그대로 처리. `--mode` 명시 시 manifest의 mode/template 덮어쓰기.

### 3. 자동 (fetch + digest 한 번에)
fetch 명령에서 `--fetch-only`를 빼면 fetch 완료 직후 자동으로 digest까지 실행.

---

## 실행 흐름

```
[--digest-from-registry 경로]
1. plan_from_registry(cfg, from_run, top, mode)
   ├─ fetch_runs.get_run(run_id) 로 video_ids 순서 가져오기
   ├─ 각 video_id에 대해 registry.find() → status='fetched' 확인
   ├─ skip_already=True 면 같은 mode로 이미 digest된 영상 제외
   └─ cache/pending.json 작성 (source_run, subdir 포함)

[공통 경로]
2. digest_runner.run_digest_only(cfg, manifest, ...)
   ├─ pending.json 읽기
   ├─ LLM 선택
   │   ├─ claude  → _run_claude_processing()
   │   ├─ gemini  → _run_gemini_processing()
   │   └─ local   → _run_local_processing()
   └─ 처리 완료 후 archive_pending() → cache/digested/{ts}.json 이동

3. 각 영상 처리
   ├─ transcript_path 파일 읽기 (트랜스크립트 텍스트)
   ├─ metadata_path JSON 읽기 (제목, 날짜, 링크 등)
   ├─ LLM 호출 (template 파일 기반 프롬프트)
   ├─ 헤더 + 결과 합쳐서 save_markdown() → output/ 저장
   ├─ mark_processed(video_id, channel_dir) → .processed.json 기록
   └─ registry.mark_digested(video_id, mode, llm, model, filepath)
```

---

## 모드

| `--mode` | 템플릿 | 특징 |
|----------|--------|------|
| `heavy` (기본) | `templates/deep_analysis.md` | 심층 해설 + 전문 원문 포함 |
| `medium` | `templates/medium_summary.md` | 줄거리 파악 중심 |
| `compact` | `templates/compact.md` | 압축 요약, 토큰 절약 |
| `compact_local` | `templates/compact_local.md` | 로컬 LLM용 compact |
| `shorts` | `templates/shorts.md` | 쇼츠 전용, 화자 분리 |

---

## LLM 선택

| `--llm` | 옵션 | 비고 |
|---------|------|------|
| `claude` (기본) | `--claude-model haiku\|sonnet\|opus` | Claude Code 서브에이전트 활용, API 키 불필요 |
| `gemini` | `--gemini-model pro\|thinking\|flash` | `.env`에 `GEMINI_API_KEY` 필요 |
| `local` | — | `config.yaml`의 `local_llm` 섹션 필요 |

---

## 출력 경로 규칙

```
output/{채널명}/{subdir}/{published_at}_{title_slug}.md
```

| subdir | 언제 |
|--------|------|
| `인기/` | popular run 기반 digest |
| `compact/` | compact 모드 (수동 정리 시) |
| (없음) | 그 외 일반 digest |

---

## pending.json 스키마

```json
{
  "mode":         "heavy",
  "template":     "./templates/deep_analysis.md",
  "channel_name": "주토피아",
  "channel_url":  "https://www.youtube.com/@jutopia_TV",
  "channel_dir":  "./output/취미/위스키/주토피아",
  "output_base":  "./output",
  "subdir":       "인기",
  "source_run":   "20260425T182416_popular",
  "pending": [
    {
      "video_id":        "fw194uOehAs",
      "title":           "신작 스프링뱅크 10 15 18 21 뽀개기",
      "published_at":    "2024-02-22",
      "url":             "https://...",
      "duration":        "PT28M12S",
      "channel_name":    "주토피아",
      "transcript_path": "./cache/transcripts/주토피아/fw194uOehAs.txt",
      "metadata_path":   "./cache/transcripts/주토피아/fw194uOehAs.json"
    }
  ],
  "skipped": []
}
```

---

## 완료 후 상태

- `output/인기/*.md` 파일 생성
- `cache/transcripts.json` 각 entry의 `digests` 배열에 기록:
  ```json
  {
    "digested_at": "2026-04-25T19:01:01",
    "mode":        "heavy",
    "llm":         "claude",
    "model":       "claude-haiku-4-5-20251001",
    "output_path": "./output/.../2024-02-22_신작_스프링뱅크.md"
  }
  ```
- `cache/pending.json` → `cache/digested/20260425T190105.json`으로 이동 (auto archive)
- `output/{채널}/.processed.json` 업데이트

---

## 주요 CLI 예시

```bash
# 인기 run 최신 기준 상위 10개 heavy, Haiku
python main.py --digest-from-registry --from-run-kind popular \
  --top 10 --mode heavy --llm claude --claude-model haiku

# 특정 run_id 지정
python main.py --digest-from-registry --from-run 20260425T182416_popular \
  --top 20 --mode medium

# 기존 pending.json으로 compact 재처리
python main.py --digest-only --mode compact

# Gemini로 자동 처리
python main.py --channel URL --popular --top 10 --mode heavy --llm gemini
```

---

## 재처리 (skip_already 우회)

같은 영상을 다른 모드로 다시 처리하려면 `--all` (fetch에서) + `plan_from_registry`의
`skip_already=False` 지정. 현재 CLI에서는 `--digest-from-registry` 시 기본 skip_already=True.
`digests` 배열에 같은 mode가 없으면 자동 포함된다.
