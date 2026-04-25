# Fetch 워크플로우

트랜스크립트를 수집해 레지스트리에 기록한다. LLM은 건드리지 않는다.

---

## 진입점

```bash
python main.py [조회 모드] --fetch-only
```

`--fetch-only` 생략 시 fetch 완료 직후 바로 digest까지 실행 (자동 모드).

---

## 조회 모드

| 옵션 | kind | 설명 |
|------|------|------|
| `--popular --top N` | `popular` | 채널 인기순 상위 N개 |
| `--latest` | `latest` | 미처리 최신 1개 |
| `--start DATE --end DATE` | `range` | 기간 내 미처리 영상 |
| `--start DATE --end DATE --all` | `range` | 기간 내 전체 (처리된 것 포함) |
| `--keyword KW` | `keyword` | 제목 키워드 검색 |
| `--url URL` | `single` | 단일 영상 URL (API 키 불필요) |

---

## 실행 흐름

```
1. YouTube Data API로 video 목록 조회
   └─ get_popular_videos / get_videos / get_latest_unprocessed / get_videos_by_keyword / get_video_by_url

2. 각 영상마다 _build_entry() 실행
   ├─ registry.add_queued(video, run_id)
   │     └─ cache/transcripts.json에 queued 상태로 등록 (중복이면 run_id만 추가)
   ├─ fetch_transcript(video_id, languages, cache_dir)
   │     ├─ 디스크 캐시 히트 → 파일에서 읽기 (네트워크 없음)
   │     └─ 캐시 없음 → youtube-transcript-api로 다운로드 후 저장
   ├─ 성공 → registry.mark_fetched(...)    status: fetched
   └─ 실패 → registry.mark_failed(...)     status: failed
             └─ 이 영상은 pending에서 제외

3. fetch_runs.save_run(run_id, kind, channel_url, params, video_ids)
   └─ cache/fetch_runs.json에 run 기록

4. _save_manifest() → cache/pending.json 작성
   └─ pending 배열 = fetch 성공한 영상들 (트랜스크립트 경로 포함)

5. --fetch-only 면 여기서 종료
   아니면 즉시 Digest 단계로 진행
```

---

## 캐시 전략

- 트랜스크립트는 `cache/transcripts/{채널명}/{video_id}.txt`에 저장
- 메타데이터는 같은 폴더에 `{video_id}.json`으로 저장
- **이미 파일이 있으면 재다운로드 없이 그대로 사용** (VPN 없이도 재실행 가능)
- `cache/transcripts.json` 레지스트리는 삭제해도 재fetch로 재건 가능

---

## 레지스트리 스키마 (transcripts.json)

```json
{
  "video_id":        "fw194uOehAs",
  "channel_name":    "주토피아",
  "title":           "신작 스프링뱅크 10 15 18 21 뽀개기",
  "published_at":    "2024-02-22",
  "url":             "https://www.youtube.com/watch?v=fw194uOehAs",
  "duration":        "PT28M12S",
  "status":          "fetched",
  "queued_at":       "2026-04-25T18:24:16",
  "fetched_at":      "2026-04-25T18:24:18",
  "failed_at":       null,
  "transcript_path": "./cache/transcripts/주토피아/fw194uOehAs.txt",
  "metadata_path":   "./cache/transcripts/주토피아/fw194uOehAs.json",
  "error":           null,
  "fetch_runs":      ["20260425T182416_popular"],
  "digests":         []
}
```

---

## Fetch Run 스키마 (fetch_runs.json)

```json
{
  "run_id":      "20260425T182416_popular",
  "ran_at":      "2026-04-25T18:24:16",
  "kind":        "popular",
  "channel_url": "https://www.youtube.com/@jutopia_TV",
  "params":      {"top": 100, "skip_processed": true},
  "video_ids":   ["fw194uOehAs", "abc123", ...]
}
```

`video_ids` 순서 = fetch 시 조회 순서 (popular → 인기순, range → 날짜 역순 등).

---

## 주요 CLI 예시

```bash
# 인기 TOP 100 fetch만 (나중에 digest)
python main.py --channel "https://www.youtube.com/@jutopia_TV" \
  --popular --top 100 --fetch-only

# 기간 fetch만
python main.py --channel URL --start 2026-04-01 --end 2026-04-25 --fetch-only

# 단일 URL (API 키 불필요)
python main.py --url "https://youtu.be/xxxx" --fetch-only
```

---

## 실패 처리

- 트랜스크립트 없는 영상 (비공개 자막 등) → `failed` 상태, pending에서 제외, 로그 기록
- IP 차단 (IpBlocked) → 에러 로그 기록, 해당 영상만 failed. VPN 연결 후 재실행 가능
- 같은 영상 재실행 시 디스크 캐시 있으면 blocked 없음
