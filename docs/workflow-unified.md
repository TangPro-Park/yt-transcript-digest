# 통합 워크플로우

전체 파이프라인은 **Fetch → Digest** 두 단계로 나뉜다.
각 단계는 독립 실행 가능하며 `cache/pending.json`이 단계 간 핸드오프 역할을 한다.

---

## 전체 흐름

```
[YouTube Data API v3]
    channels.list / playlistItems / search
          │
          ▼
  [Fetch 단계]  ─── cache/transcripts/ (디스크 캐시)
    youtube-transcript-api
    → cache/transcripts.json  (영속 레지스트리)
    → cache/fetch_runs.json   (run 묶음)
    → cache/pending.json      (현재 digest 계획)
          │
          ▼
  [Digest 단계]
    LLM (Claude / Gemini / Local)
    → output/{채널}/{subdir}/{날짜}_{제목}.md
    → cache/digested/{ts}.json  (완료 후 pending 아카이브)
    → cache/transcripts.json   (digests[] 누적)
```

---

## 단계 간 데이터 흐름

| 파일 | 역할 | 수명 |
|------|------|------|
| `cache/transcripts/` | 원본 텍스트 + 메타데이터 JSON (per video) | 영속 |
| `cache/transcripts.json` | 전체 fetch 레지스트리 + digest 이력 | 영속 |
| `cache/fetch_runs.json` | fetch 실행 단위 묶음 (run_id, kind, video_ids) | 영속 |
| `cache/pending.json` | 현재 진행 중인 digest 계획 | 1회용 (완료 시 archived) |
| `cache/digested/{ts}.json` | 완료된 pending 아카이브 | 영속 |

---

## 실행 패턴

### 패턴 A — 자동 (fetch + digest 한 번에)
```bash
python main.py --channel URL --popular --top 50 --mode heavy --llm claude
```

### 패턴 B — 분리 실행 (VPN fetch 후 나중에 digest)
```bash
# 1단계: 트랜스크립트만 수집
python main.py --channel URL --popular --top 100 --fetch-only

# 2단계: 레지스트리 기반으로 계획 수립 + digest
python main.py --digest-from-registry --from-run-kind popular --top 20 --mode heavy --claude-model haiku
```

### 패턴 C — pending.json 직접 재사용 (구 방식 호환)
```bash
python main.py --digest-only --mode compact
```

---

## 출력 디렉터리 구조

```
output/
└── {카테고리}/
    └── {채널명}/
        ├── INDEX.md
        ├── POPULAR.md
        ├── 인기/          ← --popular run에서 생성된 파일
        │   ├── 2024-02-22_신작_스프링뱅크.md
        │   └── ...
        ├── compact/       ← compact 모드
        └── {날짜}_{제목}.md
```
