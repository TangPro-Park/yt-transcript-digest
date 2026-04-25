"""
배치 출력 파일 품질 평가 스크립트
트랜스크립트 대비 output 파일을 규칙 기반으로 자동 채점
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUTPUT_DIR = ROOT / "output" / "취미" / "위스키" / "주토피아 - 어디에서도 들을 수 없는 술 이야기"
TRANSCRIPT_DIR = ROOT / "cache" / "transcripts" / "주토피아 - 어디에서도 들을 수 없는 술 이야기"

# ── 평가 규칙 ─────────────────────────────────────────────────

RULES = [
    {
        "id": "R01",
        "name": "파일 비어있지 않음",
        "check": lambda md, tx, meta: len(md.strip()) > 200,
        "critical": True,
    },
    {
        "id": "R02",
        "name": "채널 링크 포함",
        "check": lambda md, tx, meta: bool(re.search(r'\*\*채널\*\*:\s*\[.+?\]\(https?://', md)),
        "critical": False,
    },
    {
        "id": "R03",
        "name": "메타 헤더 4종 (채널/날짜/링크/길이)",
        "check": lambda md, tx, meta: all(
            f"**{k}**" in md for k in ["채널", "날짜", "링크", "길이"]
        ),
        "critical": True,
    },
    {
        "id": "R04",
        "name": "스크립트 원문 섹션 존재",
        "check": lambda md, tx, meta: "[스크립트 원문]" in md,
        "critical": True,
    },
    {
        "id": "R05",
        "name": "원문 분량 (트랜스크립트 60% 이상 재현)",
        "check": lambda md, tx, meta: _check_transcript_ratio(md, tx),
        "critical": False,
    },
    {
        "id": "R06",
        "name": "화자 표시 존재 (**화자명:**)",
        "check": lambda md, tx, meta: bool(re.search(r'\*\*.+?\*\*:', md)),
        "critical": False,
    },
    {
        "id": "R07",
        "name": "자의적 메타 코멘트 없음 (해설 완료 등)",
        "check": lambda md, tx, meta: "해설 완료" not in md and "분석 완료" not in md,
        "critical": False,
    },
    {
        "id": "R08",
        "name": "심층 해설 본문 섹션 존재",
        "check": lambda md, tx, meta: "심층 해설 본문" in md or "📖" in md,
        "critical": True,
    },
]


def _check_transcript_ratio(md: str, tx: str) -> bool:
    if not tx or len(tx) < 100:
        return True  # 트랜스크립트가 짧으면(쇼츠) 통과
    # 원문 섹션만 추출
    raw_sections = re.findall(r'\[스크립트 원문\](.*?)(?=\n---|\n##|\Z)', md, re.DOTALL)
    raw_text = " ".join(raw_sections)
    # 트랜스크립트 내 주요 단어 샘플링 (20개)
    tx_words = [w for w in re.findall(r'[가-힣]{3,}', tx) if len(w) >= 3]
    if not tx_words:
        return True
    sample = tx_words[::max(1, len(tx_words)//20)][:20]
    matched = sum(1 for w in sample if w in raw_text)
    return matched >= len(sample) * 0.5


def load_files(date_prefix: str):
    """날짜로 output 파일과 transcript 파일 매칭"""
    md_files = sorted(OUTPUT_DIR.glob(f"{date_prefix}*.md"))
    return md_files


def get_video_id_from_md(md_path: Path) -> str | None:
    content = md_path.read_text(encoding='utf-8')
    m = re.search(r'watch\?v=([A-Za-z0-9_-]+)', content)
    return m.group(1) if m else None


def get_transcript(video_id: str) -> str:
    tx_path = TRANSCRIPT_DIR / f"{video_id}.txt"
    if tx_path.exists():
        return tx_path.read_text(encoding='utf-8')
    return ""


def get_meta(video_id: str) -> dict:
    meta_path = TRANSCRIPT_DIR / f"{video_id}.json"
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}


def evaluate_file(md_path: Path) -> dict:
    md = md_path.read_text(encoding='utf-8')
    video_id = get_video_id_from_md(md_path)
    tx = get_transcript(video_id) if video_id else ""
    meta = get_meta(video_id) if video_id else {}

    results = []
    for rule in RULES:
        try:
            passed = rule["check"](md, tx, meta)
        except Exception as e:
            passed = False
        results.append({
            "id": rule["id"],
            "name": rule["name"],
            "passed": passed,
            "critical": rule["critical"],
        })

    critical_fail = any(r for r in results if r["critical"] and not r["passed"])
    score = sum(1 for r in results if r["passed"])
    return {
        "file": md_path.name,
        "video_id": video_id,
        "tx_len": len(tx),
        "md_len": len(md),
        "score": score,
        "total": len(RULES),
        "critical_fail": critical_fail,
        "results": results,
    }


def main():
    # 이번 배치(2026-02-16 ~ 2026-03-15) 파일만
    target_files = []
    for md in sorted(OUTPUT_DIR.glob("2026-02-*.md")) + sorted(OUTPUT_DIR.glob("2026-03-0*.md")) + sorted(OUTPUT_DIR.glob("2026-03-1[0-5]*.md")):
        target_files.append(md)

    if not target_files:
        print("평가할 파일 없음")
        return

    print(f"{'파일':<55} {'점수':>5}  {'트랜':>6}  {'결과'}")
    print("-" * 90)

    all_evals = []
    for md_path in sorted(set(target_files)):
        ev = evaluate_file(md_path)
        all_evals.append(ev)

        status = "XX CRITICAL" if ev["critical_fail"] else ("OK" if ev["score"] == ev["total"] else "WARN")
        tx_label = f"{ev['tx_len']:,}" if ev['tx_len'] else "없음"
        print(f"{ev['file'][:54]:<55} {ev['score']}/{ev['total']}  {tx_label:>6}자  {status}")

    # 실패 항목 상세
    print("\n" + "=" * 90)
    print("실패 규칙 상세")
    print("=" * 90)
    for ev in all_evals:
        failed = [r for r in ev["results"] if not r["passed"]]
        if failed:
            print(f"\n[FILE] {ev['file']}")
            for r in failed:
                crit = " [CRITICAL]" if r["critical"] else ""
                print(f"   X {r['id']} {r['name']}{crit}")

    # 전체 통계
    total_score = sum(e["score"] for e in all_evals)
    total_max = sum(e["total"] for e in all_evals)
    critical_fails = sum(1 for e in all_evals if e["critical_fail"])
    print(f"\n총점: {total_score}/{total_max}  |  CRITICAL 실패: {critical_fails}개 / {len(all_evals)}개 파일")


if __name__ == "__main__":
    main()
