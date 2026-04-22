# 트랜스크립트 정리 품질 테스트 프로세스

## 목적

YouTube 트랜스크립트를 LLM으로 정리할 때의 **출력 품질을 검증하고 모델 간 성능을 비교**한다.
특정 영상(픽스처)에 대한 Claude 출력을 정답지(reference)로 두고, 테스트 대상 모델의 출력과 비교한다.

### 이 테스트 프레임워크가 유용한 시나리오

| 시나리오 | 예시 |
|----------|------|
| **로컬 LLM 품질 확인** | gemma4:e4b vs Claude — 로컬 모델이 트랜스크립트를 제대로 읽는지 |
| **클라우드 모델 간 비교** | Claude vs Gemini Flash vs GPT-4o — 같은 영상, 누가 더 잘 요약하나 |
| **모드별 품질 비교** | compact vs heavy — 영상 길이 대비 적정 모드 결정 |
| **프롬프트 개선 효과 측정** | 기존 템플릿 vs 수정 템플릿 — A/B 비교 |
| **특정 채널/주제 적합성** | 경제 인터뷰 vs IT 제품 리뷰 — 채널 특성별 모델 성능 차이 |

---

## 폴더 구조

```
tests/
├── fixtures/                          # 재사용 고정 트랜스크립트
│   ├── manifest.json                  # 카테고리 등록부 (short/medium/long)
│   ├── {video_id}.txt                 # 트랜스크립트 원문
│   └── {video_id}.json                # 메타데이터 (title, url, duration 등)
│
├── runs/                              # 테스트 회차별 결과
│   └── {NNN}_{video_id}_{mode}/
│       ├── 00_meta.json               # 회차 정보 (번호, URL, 모델, 타임스탬프)
│       ├── 01_transcript.txt          # [Sub1] 사용된 트랜스크립트
│       ├── 02_prompt.txt              # [Sub1] LLM에 넘기기 직전 최종 프롬프트
│       ├── 03_result_{model}.md       # [Sub2+3] 테스트 대상 모델 출력
│       ├── 04_reference.md            # [Sub4] 정답지 (Claude 또는 상위 모델)
│       └── 05_review.md              # [Sub5] 자동 검증 + 수동 비교 리뷰
│
└── test_local_llm.py                  # 테스트 실행 스크립트 (로컬 LLM 기준, 확장 가능)
```

> **같은 픽스처로 여러 모델을 비교할 때**: 동일 video_id + mode 기준으로 테스트 회차(NNN)를 분리해서 실행하면 `03_result_{model}.md` 파일명으로 모델별 구분이 된다.

---

## 테스트 1회차 = 5개 서브 프로세스

### Sub1 — 트랜스크립트 로드 + 프롬프트 조립
- `tests/fixtures/{video_id}.txt` 에서 트랜스크립트 로드
- 해당 모드(compact/medium/heavy)의 템플릿에 트랜스크립트 삽입
- 결과물: `01_transcript.txt`, `02_prompt.txt`
- **체크포인트**: 02_prompt.txt 열어서 트랜스크립트가 실제로 삽입됐는지 확인

### Sub2 — LLM 전송
- `02_prompt.txt` 의 프롬프트를 테스트 대상 모델 API에 전송
- 로컬: `config.yaml`의 `local_llm` 설정 (Ollama 등 OpenAI 호환)
- 클라우드: `--llm` 인자로 대상 지정 가능하도록 확장 예정

### Sub3 — 결과 저장
- 모델 응답을 `03_result_{model}.md` 로 저장
- **체크포인트**: 파일 열어서 트랜스크립트 내용이 반영됐는지 육안 확인

### Sub4 — 정답지 작성 (Claude 또는 상위 모델)
- 같은 트랜스크립트를 Claude Code(`--llm claude`)로 처리해서 `04_reference.md` 작성
- 자동화 불가 → 수동 또는 yt-digest 스킬로 생성 후 복사
- 한 번 작성된 정답지는 **같은 픽스처의 다른 모델 테스트에도 재사용** 가능
- 명령 예시:
  ```bash
  python main.py --url "{영상URL}" --mode {compact|medium|heavy} --llm claude
  # 생성된 output/{채널}/{날짜}_{제목}.md 를 04_reference.md 로 복사
  ```

### Sub5 — 비교 리뷰
- 자동 검증: 어휘 포함율, hallucination 마커, 최소 길이 체크
- 수동 리뷰: `05_review.md` 체크리스트 항목을 직접 채움
- 비교 기준: `04_reference.md` (정답지) vs `03_result_{model}.md` (테스트 대상 출력)

---

## 평가 기준 (5항목 100점)

| 기준 | 배점 | 설명 |
|------|------|------|
| 사실 정확성 | 30점 | 원문의 고유명사·수치·날짜·장소가 정확히 반영됐는가 |
| 핵심 주제 포착 | 25점 | 영상의 실제 핵심 메시지를 올바르게 요약했는가 |
| Hallucination 없음 | 25점 | 원문에 없는 내용을 지어냈는가 (있으면 감점) |
| 고유 정보 보존 | 15점 | 영상에만 있는 특수 정보(이벤트·도구명 등)를 보존했는가 |
| 구조·가독성 | 5점 | 섹션 구분, 마크다운 활용 등 형식이 적절한가 |

---

## 픽스처 카테고리

| 카테고리 | 기준 | 대표 픽스처 | 특징 |
|----------|------|------------|------|
| `short`  | <15분 | fw194uOehAs (~10분) | 빠른 기능 확인용 |
| `medium` | 15~40분 | txa_8i-3cIs (~29분) | 일반적인 유튜브 영상 |
| `long`   | >40분 | P9LSUz_08g0 (~56분) | context window 스트레스 테스트 |

---

## 실행 명령

```bash
# 기본 (short + compact, 로컬 LLM)
python tests/test_local_llm.py

# 중간 영상, heavy 모드
python tests/test_local_llm.py --size medium --mode heavy

# 전체 매트릭스 (3 size × 3 mode = 9회차)
python tests/test_local_llm.py --size all --mode all

# 다른 모델과 비교
python tests/test_local_llm.py --model gemma3:1b --size short --mode compact
```

---

## 픽스처 추가 방법

1. YouTube 영상에서 트랜스크립트 수집
   ```bash
   python main.py --url "{영상URL}" --llm claude
   ```
2. `cache/transcripts/{video_id}.txt` → `tests/fixtures/` 복사
3. `tests/fixtures/manifest.json` 에 카테고리(short/medium/long) 등록
4. `04_reference.md` 는 위의 Sub4 절차로 한 번만 생성 → 이후 모든 모델 비교에 재사용

---

## 알려진 이슈 및 진단 결과

| 이슈 | 증상 | 원인 | 상태 |
|------|------|------|------|
| Ollama num_ctx 기본값 | 트랜스크립트 잘림, "스크립트 없음" 환각 | 기본 num_ctx=2048, 한국어 트랜스크립트 ~5K 토큰 → 프롬프트 42%만 전달 | **해결** — num_ctx=8192 설정 |
| gemma4:e4b instruction-following | 고유명사 무시, 형식 미준수, 점수 2~4/100 | 모델 자체 한계 (8B Q4 edge, 한국어 지시 약함) | **모델 교체로 대응** |
| qwen3.5:9b 타임아웃 | 30분 초과 응답 없음 | GTX 1050 Ti 4GB VRAM → 대부분 CPU 처리, i7-6700K 속도 한계 | **하드웨어 한계** |

## 로컬 LLM 결론 (2026-04-22)

> **현재 하드웨어(GTX 1050 Ti 4GB VRAM, i7-6700K)로는 로컬 LLM 운용이 시기상조.**

- 7B+ 모델은 VRAM 부족으로 대부분 CPU 처리 → 실용적 속도 불가
- 소형 모델(gemma4:e4b)은 속도는 되지만 한국어 instruction-following 품질 미달
- 재검토 조건: VRAM 16GB+ GPU 업그레이드 시 (RTX 4060 Ti 16GB 이상)
- 인프라는 완비됨 — 테스트 프레임워크, 평가 기준, 로컬 템플릿, num_ctx 설정 모두 준비

---

## 테스트 결과 누적 기록

| 회차 | 픽스처 | 모드 | 모델 | num_ctx | 점수 | 판정 |
|------|--------|------|------|---------|------|------|
| 001 | fw194uOehAs (short) | compact | gemma4:e4b | 2048 (기본) | 4/100 | 완전 환각 |
| 001 | fw194uOehAs (short) | compact | Claude (reference) | N/A | 95/100 | 정상 |
| 002 | fw194uOehAs (short) | compact_local | gemma4:e4b | 2048 (기본) | 2/100 | 트랜스크립트 차단 |
| 003 | fw194uOehAs (short) | compact_local | gemma4:e4b | 16384 | 2/100 | 환각 (num_ctx 해결됐으나 모델 한계) |
| 004 | fw194uOehAs (short) | compact_local | qwen3.5:9b | 8192 | N/A | 타임아웃 (하드웨어 한계) |
