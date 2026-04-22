"""
로컬 LLM 출력 품질 테스트.

테스트 1회차 = 4개 서브 프로세스:
  Sub1: 트랜스크립트 로드 + 최종 프롬프트 조립 → 01_transcript.txt, 02_prompt.txt
  Sub2: 프롬프트를 LLM에 전송
  Sub3: 모델별 결과 저장 → 03_result_{model}.md
  Sub4: 트랜스크립트 대비 결과 검증 + 리뷰 템플릿 → 04_review.md

사용법:
    python tests/test_local_llm.py                             # short + compact (기본)
    python tests/test_local_llm.py --size medium --mode heavy
    python tests/test_local_llm.py --size all --mode all       # 전체 매트릭스
    python tests/test_local_llm.py --model gemma3:1b           # 모델 비교
    python tests/test_local_llm.py --url https://youtu.be/xxx  # URL 직접 지정

픽스처 추가:
    1. cache/transcripts/{id}.txt → tests/fixtures/ 복사
    2. tests/fixtures/manifest.json 에 카테고리 등록
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

ROOT         = Path(__file__).parent.parent
FIXTURES_DIR = Path(__file__).parent / "fixtures"
RUNS_DIR     = Path(__file__).parent / "runs"
MANIFEST     = FIXTURES_DIR / "manifest.json"

sys.path.insert(0, str(ROOT))

TEMPLATES = {
    "heavy":   str(ROOT / "templates" / "deep_analysis.md"),
    "medium":  str(ROOT / "templates" / "medium_summary.md"),
    "compact": str(ROOT / "templates" / "compact.md"),
    "compact_local": str(ROOT / "templates" / "compact_local.md"),
}

SIZE_LABELS = {
    "short":  "짧은 영상 (<15분)",
    "medium": "중간 영상 (15~40분)",
    "long":   "긴 영상 (>40분)",
}


# ── 유틸 ────────────────────────────────────────────────────────────────────

def next_run_id() -> int:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    existing = [int(d.name[:3]) for d in RUNS_DIR.iterdir()
                if d.is_dir() and d.name[:3].isdigit()]
    return max(existing, default=0) + 1


def load_manifest() -> dict:
    if not MANIFEST.exists():
        raise FileNotFoundError(f"manifest.json 없음: {MANIFEST}")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def load_fixture(video_id: str) -> tuple[str, dict]:
    txt  = FIXTURES_DIR / f"{video_id}.txt"
    meta = FIXTURES_DIR / f"{video_id}.json"
    if not txt.exists():
        raise FileNotFoundError(
            f"픽스처 없음: {txt}\n"
            f"cache/transcripts/{video_id}.txt 를 tests/fixtures/ 로 복사 후 manifest.json 에 등록하세요."
        )
    transcript = txt.read_text(encoding="utf-8")
    metadata   = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
    return transcript, metadata


def build_prompt(mode: str, transcript: str, speakers: dict | None = None) -> str:
    """템플릿에 트랜스크립트를 삽입해서 최종 프롬프트 반환."""
    template = Path(TEMPLATES[mode]).read_text(encoding="utf-8")
    sp = speakers or {}
    prompt = template
    prompt = prompt.replace("{main_speaker}",  sp.get("main_speaker",  "미상"))
    prompt = prompt.replace("{mc}",            sp.get("mc",            "미상"))
    prompt = prompt.replace("{other_speaker}", sp.get("other_speaker", "없음"))
    prompt = prompt.replace("{raw_script}",    transcript)
    if "{overview_lines}" in prompt:
        from src.prompt_params import compute_params
        for k, v in compute_params(len(transcript)).items():
            prompt = prompt.replace(f"{{{k}}}", str(v))
    return prompt


def build_config(mode: str, model: str, base_url: str) -> dict:
    return {
        "processing": {"template": TEMPLATES[mode]},
        "local_llm":  {"base_url": base_url, "model": model, "temperature": 0.1, "max_tokens": 4096},
        "speakers":   {"main_speaker": "", "mc": "", "other_speaker": ""},
    }


def get_model_from_config() -> str:
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        return cfg.get("local_llm", {}).get("model", "gemma4:e4b")
    except Exception:
        return "gemma4:e4b"


def get_num_ctx_from_config() -> int | None:
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        return cfg.get("local_llm", {}).get("num_ctx")
    except Exception:
        return None


# ── 검증 ────────────────────────────────────────────────────────────────────

HALLUCINATION_MARKERS = [
    "스크립트가 제공되지 않았으므로",
    "실제 스크립트를 제공해주시면",
    "제공해주신 대화 스크립트는",
    "[실제 대화 내용을 여기에 입력]",
    "스크립트 없이는 분석이",
]

def auto_validate(result: str, transcript: str, mode: str) -> dict:
    """자동 검증. 결과 dict 반환."""
    issues = []
    min_chars = {"compact": 200, "medium": 500, "heavy": 1000, "compact_local": 200}

    if not result.strip():
        return {"passed": False, "issues": ["출력 비어 있음"], "score": 0}

    if len(result) < min_chars[mode]:
        issues.append(f"출력 너무 짧음: {len(result):,}자 (최소 {min_chars[mode]:,}자)")

    for marker in HALLUCINATION_MARKERS:
        if marker in result:
            issues.append(f"트랜스크립트 미인식 hallucination: '{marker}'")
            break

    # 트랜스크립트 핵심 어휘가 결과에 얼마나 포함됐는지 간단 측정
    words = [w for w in transcript.split() if len(w) > 3]
    sample = words[::max(1, len(words)//50)]  # 균등 샘플 50개
    overlap = sum(1 for w in sample if w in result)
    overlap_ratio = overlap / max(len(sample), 1)
    if overlap_ratio < 0.1:
        issues.append(f"원문 어휘 포함율 낮음: {overlap_ratio:.0%} (샘플 {len(sample)}개 중 {overlap}개)")

    score = max(0, 100 - len(issues) * 30)
    return {"passed": not issues, "issues": issues, "score": score,
            "overlap_ratio": f"{overlap_ratio:.0%}"}


# ── 서브 프로세스 ──────────────────────────────────────────────────────────

def sub1_prepare(run_dir: Path, transcript: str, mode: str) -> str:
    """Sub1: 트랜스크립트 저장 + 최종 프롬프트 조립 및 저장."""
    print(f"\n  [Sub1] 트랜스크립트 로드 + 프롬프트 조립")

    # 01_transcript.txt
    (run_dir / "01_transcript.txt").write_text(transcript, encoding="utf-8")
    print(f"         트랜스크립트: {len(transcript):,}자 → 01_transcript.txt")

    # 02_prompt.txt
    prompt = build_prompt(mode, transcript)
    (run_dir / "02_prompt.txt").write_text(prompt, encoding="utf-8")
    print(f"         최종 프롬프트: {len(prompt):,}자 → 02_prompt.txt")
    print(f"         (트랜스크립트 {len(transcript):,}자 + 템플릿 {len(prompt)-len(transcript):,}자)")

    return prompt


def sub2_send(prompt: str, model: str, base_url: str, num_ctx: int | None = None) -> tuple[str, float, str | None]:
    """Sub2: 프롬프트를 LLM에 전송. (result, elapsed, error) 반환."""
    print(f"\n  [Sub2] LLM 전송 중... (모델: {model})")
    t0 = time.time()
    try:
        # llm_processor 내부 build_prompt 대신 이미 조립된 prompt를 직접 전송
        from openai import OpenAI  # type: ignore
        client = OpenAI(base_url=base_url, api_key="local-dummy-key")
        extra  = {"options": {"num_ctx": num_ctx}} if num_ctx else {}
        resp   = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=4096,
            extra_body=extra,
        )
        result  = resp.choices[0].message.content or ""
        elapsed = time.time() - t0
        print(f"         완료: {elapsed:.1f}초, {len(result):,}자 출력")
        return result, elapsed, None
    except Exception as e:
        elapsed = time.time() - t0
        print(f"         오류: {e}")
        return "", elapsed, str(e)


def sub3_save_result(run_dir: Path, result: str, model: str, error: str | None) -> Path:
    """Sub3: 모델 결과 저장."""
    model_slug = model.replace(":", "_").replace("/", "_")
    out_path   = run_dir / f"03_result_{model_slug}.md"
    content    = result if result else f"[오류] {error}"
    out_path.write_text(content, encoding="utf-8")
    print(f"\n  [Sub3] 결과 저장: {out_path.name} ({len(result):,}자)")
    return out_path


def sub4_reference(run_dir: Path, mode: str):
    """Sub4: 정답지 플레이스홀더 생성 (Claude 출력을 수동으로 붙여넣기)."""
    ref_path = run_dir / "04_reference.md"
    if ref_path.exists():
        print(f"\n  [Sub4] 04_reference.md 이미 존재 — 유지")
        return
    content = f"""# 정답지 (Reference)

> **작성 방법:**
> 1. 같은 트랜스크립트를 Claude Code로 처리:
>    ```bash
>    python main.py --url "{{영상URL}}" --mode {mode} --llm claude
>    ```
> 2. 생성된 `output/{{채널}}/{{날짜}}_{{제목}}.md` 내용을 이 파일에 붙여넣기

<!-- 아래에 정답지 내용을 붙여넣으세요 -->
"""
    ref_path.write_text(content, encoding="utf-8")
    print(f"\n  [Sub4] 정답지 플레이스홀더 생성 → 04_reference.md")
    print(f"         Claude로 처리 후 내용을 04_reference.md에 붙여넣으세요")


def sub5_review(run_dir: Path, transcript: str, result: str,
                model: str, mode: str, elapsed: float) -> dict:
    """Sub5: 자동 검증 + 리뷰 템플릿 저장."""
    print(f"\n  [Sub5] 결과 리뷰")
    validation = auto_validate(result, transcript, mode)
    tag = "[OK]" if validation["passed"] else "[NG]"
    print(f"         자동 검증: {tag}  어휘 포함율: {validation.get('overlap_ratio','?')}")
    for issue in validation["issues"]:
        print(f"         -> {issue}")

    review = f"""# 결과 리뷰

## 자동 검증
- 판정: {tag}
- 어휘 포함율: {validation.get('overlap_ratio', '?')}
- 소요 시간: {elapsed:.1f}초
- 출력 길이: {len(result):,}자
- 이슈: {', '.join(validation['issues']) if validation['issues'] else '없음'}

## 수동 리뷰 체크리스트
<!-- 아래 항목을 직접 채워주세요 -->

### 트랜스크립트 반영도
- [ ] 핵심 주장/논점이 정확히 반영됐나?
- [ ] 화자 구분이 올바른가?
- [ ] 원문에 없는 내용을 지어냈나? (hallucination)

### 내용 품질
- [ ] 요약이 원문 맥락을 유지하는가?
- [ ] 중요한 내용이 누락됐나?
- [ ] 전문 용어가 올바르게 처리됐나?

### 종합 평점 (1~5)
평점: ___

### 메모
(자유롭게 작성)

---
*자동 생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
*모델: {model} | 모드: {mode}*
"""
    (run_dir / "05_review.md").write_text(review, encoding="utf-8")
    return validation


# ── 단일 회차 실행 ─────────────────────────────────────────────────────────

def run_test(run_id: int, video_id: str, url: str, mode: str,
             model: str, base_url: str, size_label: str) -> dict:
    """1개 (video_id, mode, model) 조합을 4개 서브 프로세스로 실행."""

    run_name = f"{run_id:03d}_{video_id}_{mode}"
    run_dir  = RUNS_DIR / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    transcript, meta = load_fixture(video_id)
    title = meta.get("title", video_id)

    print(f"\n{'='*65}")
    print(f"테스트 #{run_id:03d}  |  {size_label}  |  mode={mode}")
    print(f"영상: {title}")
    print(f"URL:  {url or meta.get('url', '?')}")
    print(f"모델: {model}")
    print(f"폴더: tests/runs/{run_name}/")
    print(f"{'='*65}")

    # 00_meta.json
    meta_info = {
        "run_id":     run_id,
        "video_id":   video_id,
        "url":        url or meta.get("url", ""),
        "title":      title,
        "mode":       mode,
        "model":      model,
        "size":       size_label,
        "timestamp":  datetime.now().isoformat(),
    }
    (run_dir / "00_meta.json").write_text(
        json.dumps(meta_info, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    prompt          = sub1_prepare(run_dir, transcript, mode)
    result, elapsed, error = sub2_send(prompt, model, base_url, num_ctx=get_num_ctx_from_config())
    sub3_save_result(run_dir, result, model, error)
    sub4_reference(run_dir, mode)
    validation      = sub5_review(run_dir, transcript, result, model, mode, elapsed)

    print(f"\n  -> 전체 완료: tests/runs/{run_name}/")
    return {
        "run_id":   run_id,
        "run_name": run_name,
        "mode":     mode,
        "model":    model,
        "elapsed":  elapsed,
        "chars_in":  len(transcript),
        "chars_out": len(result),
        "passed":    validation["passed"],
        "issues":    validation["issues"],
    }


# ── 매트릭스 요약 ──────────────────────────────────────────────────────────

def print_summary(results: list[dict]):
    print(f"\n{'='*65}")
    print(f"최종 요약: {sum(r['passed'] for r in results)}/{len(results)} 통과")
    print(f"{'='*65}")
    print(f"{'#':>4}  {'mode':<8}  {'모델':<20}  {'시간':>6}  {'입력':>8}  {'출력':>8}  결과")
    print(f"{'-'*65}")
    for r in results:
        tag = "[OK]" if r["passed"] else "[NG]"
        print(f"{r['run_id']:>4}  {r['mode']:<8}  {r['model']:<20}  "
              f"{r['elapsed']:>5.1f}s  {r['chars_in']:>7,}자  {r['chars_out']:>7,}자  {tag}")
    if any(not r["passed"] for r in results):
        print()
        for r in results:
            if not r["passed"]:
                print(f"  #{r['run_id']:03d} 이슈:")
                for i in r["issues"]:
                    print(f"    -> {i}")


# ── 진입점 ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="로컬 LLM 출력 품질 테스트")
    parser.add_argument("--size",     default="short",
                        choices=["short", "medium", "long", "all"])
    parser.add_argument("--mode",     default="compact",
                        choices=["compact", "medium", "heavy", "compact_local", "all"])
    parser.add_argument("--model",    default=None)
    parser.add_argument("--base-url", default="http://localhost:11434/v1", dest="base_url")
    parser.add_argument("--url",      default=None, help="타겟 URL (메타 기록용)")
    args = parser.parse_args()

    model    = args.model or get_model_from_config()
    manifest = load_manifest()
    sizes    = ["short", "medium", "long"] if args.size == "all" else [args.size]
    modes    = ["compact", "medium", "heavy"] if args.mode == "all" else [args.mode]

    print(f"\n{'#'*65}")
    print(f"  로컬 LLM 테스트 시작")
    print(f"  크기: {', '.join(sizes)}  |  모드: {', '.join(modes)}")
    print(f"  모델: {model}  |  엔드포인트: {args.base_url}")
    print(f"{'#'*65}")

    results = []
    for size in sizes:
        for mode in modes:
            if size not in manifest:
                print(f"[건너뜀] manifest에 '{size}' 카테고리 없음")
                continue
            info   = manifest[size]
            run_id = next_run_id()
            r = run_test(
                run_id    = run_id,
                video_id  = info["video_id"],
                url       = args.url or "",
                mode      = mode,
                model     = model,
                base_url  = args.base_url,
                size_label= SIZE_LABELS[size],
            )
            results.append(r)

    print_summary(results)
    sys.exit(0 if all(r["passed"] for r in results) else 1)


if __name__ == "__main__":
    main()
