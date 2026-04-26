"""
YouTube Transcript Digest — 파이프라인 오케스트레이터

사용법:
  # 단일 URL (API 키 불필요)
  python main.py --url "https://youtu.be/xxxx"

  # 모드 1: 채널에서 가장 최근 미처리 영상 1개
  python main.py --channel "https://youtube.com/@handle" --latest

  # 모드 2: 기간 내 미처리 영상
  python main.py --channel "https://youtube.com/@handle" --start 2026-01-01 --end 2026-04-18

  # 모드 3: 키워드 검색
  python main.py --channel "https://youtube.com/@handle" --keyword "클로드" [--start ... --end ...]

  # 모드 4: 기간 내 전체 (이미 처리된 것도 포함)
  python main.py --channel "https://youtube.com/@handle" --start 2026-01-01 --end 2026-04-18 --all

  # INDEX.md 재생성
  python main.py --index --channel "https://youtube.com/@handle"
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, date

import yaml
from dotenv import load_dotenv

from src.discover import (
    get_video_by_url,
    get_videos,
    get_latest_unprocessed,
    get_videos_by_keyword,
    get_popular_videos,
)
from src.storage import generate_index, load_processed, mark_processed, sanitize_dirname, save_markdown
from src.transcript import CACHE_DIR as TRANSCRIPT_CACHE_DIR, fetch_transcript
from src.llm import process_with_gemini, print_gemini_model_info, GEMINI_MODELS
from src.claude_cli import process_with_claude_cli, CLAUDE_MODELS, DEFAULT_MODEL as CLAUDE_DEFAULT_MODEL
from src import registry, fetch_runs

# Windows 콘솔 cp949 → utf-8 강제
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')


def setup_logging():
    os.makedirs('./logs', exist_ok=True)
    log_file = f"./logs/{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False)),
        ],
    )


def load_config(path='./config.yaml'):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def _build_entry(video, languages, run_id=None):
    """트랜스크립트 fetch 후 pending 항목 반환. 실패 시 (None, video) 반환."""
    metadata = {
        'video_id':          video['video_id'],
        'title':             video.get('title', ''),
        'channel_name':      video.get('channel_name', ''),
        'published_at':      video.get('published_at', ''),
        'duration':          video.get('duration', ''),
        'url':               video.get('url', ''),
        'description':       video.get('description', ''),
        'tags':              video.get('tags', []),
        'chapters':          video.get('chapters', []),
        'view_count':        video.get('view_count', 0),
        'like_count':        video.get('like_count', 0),
        'topic_categories':  video.get('topic_categories', []),
    }
    channel_name = video.get('channel_name', 'unknown')
    cache_dir = os.path.join(TRANSCRIPT_CACHE_DIR, sanitize_dirname(channel_name))
    registry.add_queued(video, run_id=run_id)
    text = fetch_transcript(video['video_id'], languages, cache_dir=cache_dir, metadata=metadata)
    if text is None:
        registry.mark_failed(video['video_id'], 'no transcript')
        return None, video
    video['transcript_path'] = os.path.join(cache_dir, f"{video['video_id']}.txt")
    video['metadata_path']   = os.path.join(cache_dir, f"{video['video_id']}.json")
    registry.mark_fetched(video['video_id'], video['transcript_path'], video['metadata_path'])
    return video, None


TEMPLATES = {
    'heavy':         './templates/deep_analysis.md',
    'medium':        './templates/medium_summary.md',
    'compact':       './templates/compact.md',
    'compact_local': './templates/compact_local.md',
    'shorts':        './templates/shorts.md',
}


def _save_manifest(cfg, channel_name, pending, skipped, mode='heavy', channel_url='', subdir=''):
    os.makedirs('./cache', exist_ok=True)
    channel_dir = os.path.join(cfg['output']['base_dir'], sanitize_dirname(channel_name))
    manifest = {
        'channel_name': channel_name,
        'channel_url': channel_url,
        'channel_dir': channel_dir,
        'template': TEMPLATES[mode],
        'mode': mode,
        'output_base': cfg['output']['base_dir'],
        'subdir': subdir,
        'pending': pending,
        'skipped': [v['video_id'] for v in skipped],
    }
    with open('./cache/pending.json', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest


def _print_summary(manifest, skipped, llm='claude'):
    logger = logging.getLogger('main')
    pending = manifest['pending']

    if skipped:
        logger.warning("트랜스크립트 없는 영상:")
        for v in skipped:
            logger.warning(f"  - [{v['video_id']}] {v['title']}")

    sep = "=" * 60
    print(f"\n{sep}")
    print(f"Fetch 완료  |  채널: {manifest['channel_name']}  |  LLM: {llm}")
    print(f"  대기 {len(pending)}개  |  스킵 {len(skipped)}개")
    if pending:
        for v in pending:
            print(f"  - [{v['published_at']}] {v['title']}")
    print(f"  매니페스트: ./cache/pending.json")
    print(f"{sep}")
    if llm == 'claude':
        print("\n[다음 단계] Claude Code에서 pending.json을 읽어")
        print("각 transcript_path 파일을 deep_analysis.md 템플릿으로 처리하세요.")


def _run_local_processing(manifest, cfg):
    """로컬 LLM(OpenAI 호환 API)으로 pending 항목을 처리하고 output 파일로 저장."""
    from src.llm_processor import process_with_local_llm

    channel_dir  = manifest['channel_dir']
    output_base  = manifest['output_base']
    channel_name = manifest['channel_name']
    template     = manifest['template']

    # llm_processor는 config['processing']['template']을 읽으므로 manifest의 템플릿을 주입
    local_cfg = dict(cfg)
    local_cfg['processing'] = {**local_cfg.get('processing', {}), 'template': template}

    model     = local_cfg.get('local_llm', {}).get('model', 'local')
    is_shorts = manifest.get('mode') == 'shorts'
    ch_url    = manifest.get('channel_url', '')
    subdir    = manifest.get('subdir', '')
    saved = []
    for item in manifest['pending']:
        title        = item.get('title', item['video_id'])
        published_at = item.get('published_at', '')
        url          = item.get('url', '')
        duration     = item.get('duration', '') or ''
        channel      = item.get('channel_name', channel_name)
        ch_display   = f"[{channel}]({ch_url})" if ch_url else channel

        with open(item['transcript_path'], 'r', encoding='utf-8') as f:
            transcript = f.read()

        result = process_with_local_llm(transcript, local_cfg)

        dur_display  = f"{duration} (쇼츠)" if is_shorts and duration else ('(쇼츠)' if is_shorts else duration)
        file_prefix  = '(쇼츠)_' if is_shorts else ''
        header = (
            f"# {title}\n\n"
            f"**채널**: {ch_display}\n"
            f"**날짜**: {published_at}\n"
            f"**링크**: {url}\n"
            f"**길이**: {dur_display}\n\n"
            f"---\n\n"
        )
        filepath = save_markdown(header + result, channel_name, published_at, title, output_base, prefix=file_prefix, subdir=subdir)
        mark_processed(item['video_id'], channel_dir)
        registry.mark_digested(item['video_id'], manifest.get('mode', ''), 'local', model, filepath)
        saved.append(filepath)
        print(f"  ✅ [{model}] {title} → {filepath}")

    return saved


def _run_claude_processing(manifest, claude_model):
    """claude CLI subprocess로 pending 항목을 처리하고 output 파일로 저장."""
    channel_dir  = manifest['channel_dir']
    output_base  = manifest['output_base']
    channel_name = manifest['channel_name']
    template     = manifest['template']
    is_shorts    = manifest.get('mode') == 'shorts'

    ch_url = manifest.get('channel_url', '')
    subdir = manifest.get('subdir', '')
    saved = []
    for item in manifest['pending']:
        title        = item.get('title', item['video_id'])
        published_at = item.get('published_at', '')
        url          = item.get('url', '')
        duration     = item.get('duration', '') or ''
        channel      = item.get('channel_name', channel_name)
        ch_display   = f"[{channel}]({ch_url})" if ch_url else channel

        result = process_with_claude_cli(item, template, claude_model)

        dur_display  = f"{duration} (쇼츠)" if is_shorts and duration else ('(쇼츠)' if is_shorts else duration)
        file_prefix  = '(쇼츠)_' if is_shorts else ''
        header = (
            f"# {title}\n\n"
            f"**채널**: {ch_display}\n"
            f"**날짜**: {published_at}\n"
            f"**링크**: {url}\n"
            f"**길이**: {dur_display}\n\n"
            f"---\n\n"
        )
        filepath = save_markdown(header + result, channel_name, published_at, title, output_base, prefix=file_prefix, subdir=subdir)
        mark_processed(item['video_id'], channel_dir)
        model_id = CLAUDE_MODELS.get(claude_model, claude_model)
        registry.mark_digested(item['video_id'], manifest.get('mode', ''), 'claude', model_id, filepath)
        saved.append(filepath)
        print(f"  ✅ [{model_id}] {title} → {filepath}")

    return saved


def _run_gemini_processing(manifest, gemini_api_key, gemini_model):
    """Gemini API로 pending 항목을 처리하고 output 파일로 저장."""
    channel_dir  = manifest['channel_dir']
    output_base  = manifest['output_base']
    channel_name = manifest['channel_name']
    template     = manifest['template']
    is_shorts    = manifest.get('mode') == 'shorts'

    ch_url = manifest.get('channel_url', '')
    subdir = manifest.get('subdir', '')
    saved = []
    for item in manifest['pending']:
        title        = item.get('title', item['video_id'])
        published_at = item.get('published_at', '')
        url          = item.get('url', '')
        duration     = item.get('duration', '') or ''
        channel      = item.get('channel_name', channel_name)
        ch_display   = f"[{channel}]({ch_url})" if ch_url else channel

        result, used_tier = process_with_gemini(item, template, gemini_api_key, gemini_model)

        dur_display  = f"{duration} (쇼츠)" if is_shorts and duration else ('(쇼츠)' if is_shorts else duration)
        file_prefix  = '(쇼츠)_' if is_shorts else ''
        header = (
            f"# {title}\n\n"
            f"**채널**: {ch_display}\n"
            f"**날짜**: {published_at}\n"
            f"**링크**: {url}\n"
            f"**길이**: {dur_display}\n\n"
            f"---\n\n"
        )
        filepath = save_markdown(header + result, channel_name, published_at, title, output_base, prefix=file_prefix, subdir=subdir)
        mark_processed(item['video_id'], channel_dir)
        registry.mark_digested(item['video_id'], manifest.get('mode', ''), 'gemini', used_tier, filepath)
        saved.append(filepath)
        print(f"  ✅ [{used_tier}] {title} → {filepath}")

    return saved


def _process_video_list(videos, cfg, processed_ids=None, mode='heavy', llm='claude', gemini_model='pro', claude_model=CLAUDE_DEFAULT_MODEL, channel_url='', fetch_only=False, kind=None, run_params=None, subdir=''):
    """영상 목록에서 트랜스크립트를 수집하고 manifest를 저장 (또는 Gemini로 직접 처리).

    fetch_only=True 시 트랜스크립트 수집 + manifest 저장까지만, LLM 처리 스킵.
    kind 지정 시 fetch run으로 묶어 cache/fetch_runs.json에 기록한다.
    """
    languages = cfg['youtube'].get('languages', ['ko', 'en'])
    channel_name = videos[0]['channel_name'] if videos else 'unknown'

    run_id = fetch_runs.make_run_id(kind) if kind else None

    pending, skipped = [], []
    attempted_ids = []
    for video in videos:
        if processed_ids and video['video_id'] in processed_ids:
            logging.getLogger('main').info(f"스킵 (이미 처리됨): {video['title']}")
            continue
        attempted_ids.append(video['video_id'])
        entry, skip = _build_entry(video, languages, run_id=run_id)
        (pending if entry else skipped).append(entry or skip)

    if run_id:
        fetch_runs.save_run(
            run_id=run_id,
            kind=kind,
            channel_url=channel_url,
            params=run_params or {},
            video_ids=attempted_ids,
        )

    manifest = _save_manifest(cfg, channel_name, pending, skipped, mode=mode, channel_url=channel_url, subdir=subdir)
    _print_summary(manifest, skipped, llm=llm)

    if fetch_only:
        if run_id:
            print(f"[fetch run] {run_id}  ({len(attempted_ids)}개 영상)")
        print("\n[--fetch-only] 트랜스크립트 수집 완료. --digest-only로 처리하세요.")
        return manifest

    if llm == 'claude' and pending:
        sep = "=" * 60
        print(f"\n{sep}")
        print(f"Claude CLI 처리 시작  |  모드: {mode}  |  모델: {CLAUDE_MODELS.get(claude_model, claude_model)}")
        print(f"{sep}")
        saved = _run_claude_processing(manifest, claude_model)
        print(f"\n완료: {len(saved)}개 파일 저장")

    elif llm == 'gemini' and pending:
        gemini_api_key = _load_env_key('GEMINI_API_KEY')
        if not gemini_api_key:
            print("오류: .env에 GEMINI_API_KEY를 설정하세요.")
            sys.exit(1)
        sep = "=" * 60
        print(f"\n{sep}")
        print(f"Gemini 처리 시작  |  모드: {mode}  |  티어: {gemini_model}")
        print(f"{sep}")
        saved = _run_gemini_processing(manifest, gemini_api_key, gemini_model)
        print(f"\n완료: {len(saved)}개 파일 저장")

    elif llm == 'local' and pending:
        if 'local_llm' not in cfg:
            print("오류: config.yaml에 local_llm 섹션이 필요합니다.")
            sys.exit(1)
        llm_cfg  = cfg['local_llm']
        sep = "=" * 60
        print(f"\n{sep}")
        print(f"로컬 LLM 처리 시작  |  모드: {mode}  |  모델: {llm_cfg.get('model', '?')} @ {llm_cfg.get('base_url', '?')}")
        print(f"{sep}")
        saved = _run_local_processing(manifest, cfg)
        print(f"\n완료: {len(saved)}개 파일 저장")

    return manifest


# ── 모드별 실행 함수 ─────────────────────────────────────────

def run_single(video_url, cfg, api_key=None, mode='heavy', llm='claude', gemini_model='pro', claude_model=CLAUDE_DEFAULT_MODEL, fetch_only=False):
    """단일 URL."""
    logger = logging.getLogger('main')
    logger.info(f"=== 단일 영상 [{mode}|{llm}]: {video_url} ===")
    video = get_video_by_url(video_url, api_key)
    logger.info(f"제목: {video['title']} | 날짜: {video['published_at']}")
    return _process_video_list(
        [video], cfg, mode=mode, llm=llm, gemini_model=gemini_model, claude_model=claude_model,
        fetch_only=fetch_only, kind='single', run_params={'url': video_url},
    )


def run_latest(channel_url, cfg, api_key, mode='heavy', llm='claude', gemini_model='pro', claude_model=CLAUDE_DEFAULT_MODEL, fetch_only=False):
    """모드 1: 채널의 가장 최근 미처리 영상 1개."""
    logger = logging.getLogger('main')
    logger.info(f"=== 최신 미처리 영상 조회 [{mode}|{llm}]: {channel_url} ===")

    channel_dir = _guess_channel_dir(cfg, channel_url, api_key)
    processed = load_processed(channel_dir)

    videos = get_latest_unprocessed(api_key, channel_url, processed)
    if not videos:
        print("모든 최근 영상이 이미 처리되었습니다.")
        return None
    return _process_video_list(
        videos, cfg, mode=mode, llm=llm, gemini_model=gemini_model, claude_model=claude_model,
        channel_url=channel_url, fetch_only=fetch_only,
        kind='latest', run_params={},
    )


def run_range(channel_url, start_date, end_date, cfg, api_key, skip_processed=True, mode='heavy', llm='claude', gemini_model='pro', claude_model=CLAUDE_DEFAULT_MODEL, fetch_only=False):
    """모드 2 (미처리만) / 모드 4 (전체)."""
    logger = logging.getLogger('main')
    label = "미처리" if skip_processed else "전체"
    logger.info(f"=== 기간 {label} 조회 [{mode}|{llm}]: {start_date} ~ {end_date} ===")

    videos = get_videos(
        api_key=api_key,
        channel_url=channel_url,
        start_date=start_date,
        end_date=end_date,
        max_videos=cfg['youtube'].get('max_videos', 50),
    )
    if not videos:
        print("기간 내 영상이 없습니다.")
        return None

    channel_dir = os.path.join(cfg['output']['base_dir'], sanitize_dirname(videos[0]['channel_name']))
    processed = load_processed(channel_dir) if skip_processed else set()
    return _process_video_list(
        videos, cfg, processed_ids=processed, mode=mode, llm=llm,
        gemini_model=gemini_model, claude_model=claude_model,
        channel_url=channel_url, fetch_only=fetch_only,
        kind='range', run_params={'start': start_date, 'end': end_date, 'skip_processed': skip_processed},
    )


def run_keyword(channel_url, keyword, cfg, api_key, start_date=None, end_date=None, skip_processed=True, mode='heavy', llm='claude', gemini_model='pro', claude_model=CLAUDE_DEFAULT_MODEL, fetch_only=False):
    """모드 3: 키워드 검색."""
    logger = logging.getLogger('main')
    logger.info(f"=== 키워드 검색 [{mode}|{llm}]: '{keyword}' ===")

    videos = get_videos_by_keyword(
        api_key=api_key,
        channel_url=channel_url,
        keyword=keyword,
        start_date=start_date,
        end_date=end_date,
        max_results=cfg['youtube'].get('max_videos', 50),
    )
    if not videos:
        print(f"키워드 '{keyword}'에 해당하는 영상이 없습니다.")
        return None

    channel_dir = os.path.join(cfg['output']['base_dir'], sanitize_dirname(videos[0]['channel_name']))
    processed = load_processed(channel_dir) if skip_processed else set()
    return _process_video_list(
        videos, cfg, processed_ids=processed, mode=mode, llm=llm,
        gemini_model=gemini_model, claude_model=claude_model,
        channel_url=channel_url, fetch_only=fetch_only,
        kind='keyword', run_params={'keyword': keyword, 'start': start_date, 'end': end_date, 'skip_processed': skip_processed},
    )


def run_popular(channel_url, cfg, api_key, top=50, skip_processed=True, mode='heavy', llm='claude', gemini_model='pro', claude_model=CLAUDE_DEFAULT_MODEL, fetch_only=False):
    """인기순 상위 N개 영상 처리 + POPULAR.md 인덱스 저장."""
    logger = logging.getLogger('main')
    logger.info(f"=== 인기순 TOP {top} [{mode}|{llm}]: {channel_url} ===")

    videos = get_popular_videos(api_key, channel_url, max_results=top)
    if not videos:
        print("인기 영상을 가져올 수 없습니다.")
        return None

    channel_name = videos[0]['channel_name']
    channel_dir = os.path.join(cfg['output']['base_dir'], sanitize_dirname(channel_name))
    processed = load_processed(channel_dir) if skip_processed else set()

    manifest = _process_video_list(
        videos, cfg, processed_ids=processed,
        mode=mode, llm=llm, gemini_model=gemini_model, claude_model=claude_model,
        channel_url=channel_url, fetch_only=fetch_only,
        kind='popular', run_params={'top': top, 'skip_processed': skip_processed},
        subdir='인기',
    )

    # POPULAR.md 인덱스 저장
    today = date.today().isoformat()
    ch_url = channel_url
    lines = [
        f"# {channel_name} 인기 영상순 TOP {top}\n",
        f"**채널**: [{channel_name}]({ch_url})  ",
        f"**업데이트**: {today}\n",
        "| 순위 | 제목 | 링크 |",
        "|------|------|------|",
    ]
    for rank, v in enumerate(videos, 1):
        title = v['title']
        yt_url = v['url']
        # 처리된 파일 찾기
        slug = re.sub(r'[\\/*?:"<>|]', '_', title).strip().replace(' ', '_')
        slug = re.sub(r'_+', '_', slug)[:60]
        import glob as _glob
        matches = (
            _glob.glob(os.path.join(channel_dir, f"{v['published_at']}_{slug}*.md")) or
            _glob.glob(os.path.join(channel_dir, f"(쇼츠)_{v['published_at']}_{slug}*.md"))
        )
        if matches:
            rel = os.path.basename(matches[0])
            link = f"[분석](./{rel})"
        else:
            link = f"[YouTube]({yt_url})"
        lines.append(f"| {rank} | {title} | {link} |")

    popular_path = os.path.join(channel_dir, "POPULAR.md")
    os.makedirs(channel_dir, exist_ok=True)
    with open(popular_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(f"\nPOPULAR.md 저장: {popular_path}")
    return manifest


def _guess_channel_dir(cfg, channel_url, api_key):
    """processed.json 경로 추정용.

    1) URL의 @handle로 output 디렉터리 직접 매칭 시도 (API 호출 없이)
    2) 실패 시 YouTube API로 채널명 조회
    """
    base = cfg['output']['base_dir']
    m = re.search(r'youtube\.com/@([^/?&\s]+)', channel_url)
    if m and os.path.isdir(base):
        handle = m.group(1).lower()
        for name in os.listdir(base):
            if handle in name.lower() and os.path.isdir(os.path.join(base, name)):
                return os.path.join(base, name)

    if not api_key:
        raise ValueError("채널 디렉터리를 추정할 수 없습니다. YOUTUBE_API_KEY를 설정하거나 이미 처리된 채널 폴더가 있어야 합니다.")

    from src.discover import _get_channel_info
    from googleapiclient.discovery import build
    youtube = build('youtube', 'v3', developerKey=api_key)
    _, channel_name, _ = _get_channel_info(youtube, channel_url)
    return os.path.join(base, sanitize_dirname(channel_name))


# ── CLI ──────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        description='YouTube Transcript Digest',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument('--url', metavar='URL', help='단일 영상 URL')
    p.add_argument('--channel', metavar='URL', help='채널 URL (모드 1~4)')
    p.add_argument('--mode', choices=['heavy', 'medium', 'compact', 'compact_local', 'shorts'], default='heavy',
                   help='정리 모드: heavy=심층분석(기본), medium=줄거리파악, compact=압축요약, shorts=화자분리 전문(쇼츠 전용)')
    p.add_argument('--latest', action='store_true', help='[모드 1] 최신 미처리 영상 1개')
    p.add_argument('--start', metavar='YYYY-MM-DD', help='시작일')
    p.add_argument('--end', metavar='YYYY-MM-DD', help='종료일 (기본: 오늘)')
    p.add_argument('--keyword', metavar='KW', help='[모드 3] 키워드 검색')
    p.add_argument('--popular', action='store_true', help='인기순 상위 영상 처리 + POPULAR.md 생성')
    p.add_argument('--top', type=int, default=50, metavar='N', help='인기순 상위 N개 (기본 50, --popular 전용)')
    p.add_argument('--all', dest='all_videos', action='store_true',
                   help='[모드 4] 이미 처리된 영상도 포함')
    p.add_argument('--index', action='store_true', help='INDEX.md 재생성')
    # fetch / digest 분리 실행
    p.add_argument('--fetch-only', dest='fetch_only', action='store_true',
                   help='트랜스크립트만 수집하고 cache/pending.json 저장 (LLM 처리 스킵)')
    p.add_argument('--digest-only', dest='digest_only', action='store_true',
                   help='cache/pending.json 읽어 LLM 처리만 실행 '
                        '(--mode 명시 시 manifest의 mode/template 덮어쓰기)')
    # registry 기반 digest 계획
    p.add_argument('--digest-from-registry', dest='digest_from_registry', action='store_true',
                   help='fetch run의 video_ids 순서로 pending.json을 작성하고 다이제스트 실행')
    p.add_argument('--from-run', dest='from_run', metavar='RUN_ID', default='latest',
                   help="대상 fetch run: 'latest'(기본) 또는 명시적 run_id")
    p.add_argument('--from-run-kind', dest='from_run_kind',
                   choices=['popular', 'range', 'keyword', 'latest', 'single'], default=None,
                   help="--from-run latest와 함께 쓰면 해당 kind 중 최신 run 선택")
    # LLM 선택
    p.add_argument('--llm', choices=['claude', 'gemini', 'local'], default='claude',
                   help='LLM 엔진: claude=Claude Code 스킬(기본), gemini=Gemini API 자동 처리, '
                        'local=OpenAI 호환 로컬 LLM (config.yaml의 local_llm 섹션)')
    p.add_argument('--gemini-model', dest='gemini_model',
                   choices=list(GEMINI_MODELS.keys()), default='pro',
                   help='Gemini 티어: pro(기본,일25회) / thinking(일500회) / flash(일1500회). '
                        '미지정 시 pro→thinking→flash 자동 폴백')
    p.add_argument('--gemini-info', action='store_true', help='Gemini 모델 티어 안내 출력')
    p.add_argument('--claude-model', dest='claude_model',
                   choices=list(CLAUDE_MODELS.keys()), default=CLAUDE_DEFAULT_MODEL,
                   help=f'Claude 모델: haiku(기본,빠름/저비용) / sonnet / opus. --llm claude 전용')
    return p


def _load_env_key(name):
    """env 변수 로드. .env.example의 플레이스홀더(`your_...`)는 None으로 취급."""
    v = os.getenv(name)
    if not v or v.startswith('your_'):
        return None
    return v


def main():
    setup_logging()
    load_dotenv()

    args = build_parser().parse_args()
    cfg = load_config()
    api_key = _load_env_key('YOUTUBE_API_KEY')

    today = date.today().isoformat()

    # ── Gemini 티어 안내
    if args.gemini_info:
        print_gemini_model_info()
        return

    # ── --digest-from-registry: fetch run 기반 plan → digest
    if args.digest_from_registry:
        from src.plan import plan_from_registry
        from src.digest_runner import run_digest_only
        manifest = plan_from_registry(
            cfg=cfg,
            from_run=args.from_run,
            from_run_kind=args.from_run_kind,
            top=args.top if '--top' in sys.argv else None,
            mode=args.mode,
        )
        if manifest is None:
            return
        run_digest_only(
            cfg=cfg,
            mode_override=None,  # plan_from_registry가 이미 mode를 반영
            llm=args.llm,
            gemini_model=args.gemini_model,
            claude_model=args.claude_model,
            run_claude=_run_claude_processing,
            run_gemini=_run_gemini_processing,
            run_local=_run_local_processing,
            load_env_key=_load_env_key,
            claude_models=CLAUDE_MODELS,
        )
        return

    # ── --digest-only: pending.json 읽어 LLM만 실행
    if args.digest_only:
        from src.digest_runner import run_digest_only
        # --mode를 사용자가 명시했는지 체크 (미명시 시 manifest의 mode 유지)
        mode_override = args.mode if '--mode' in sys.argv else None
        run_digest_only(
            cfg=cfg,
            mode_override=mode_override,
            llm=args.llm,
            gemini_model=args.gemini_model,
            claude_model=args.claude_model,
            run_claude=_run_claude_processing,
            run_gemini=_run_gemini_processing,
            run_local=_run_local_processing,
            load_env_key=_load_env_key,
            claude_models=CLAUDE_MODELS,
        )
        return

    # ── INDEX 재생성
    if args.index:
        if not args.channel:
            print("오류: --channel을 함께 지정하세요.")
            sys.exit(1)
        channel_dir = _guess_channel_dir(cfg, args.channel, api_key)
        channel_name = os.path.basename(channel_dir)
        path = generate_index(channel_name, cfg['output']['base_dir'])
        print(f"INDEX.md 생성: {path}")
        return

    # ── 단일 URL
    if args.url:
        run_single(args.url, cfg, api_key, mode=args.mode, llm=args.llm, gemini_model=args.gemini_model, claude_model=args.claude_model, fetch_only=args.fetch_only)
        return

    # ── 채널 모드 공통 체크
    channel = args.channel or cfg['youtube'].get('channel_url')
    if not channel:
        print("오류: --channel 또는 config.yaml의 channel_url을 설정하세요.")
        sys.exit(1)
    if not api_key:
        print("오류: .env에 YOUTUBE_API_KEY를 설정하세요.")
        sys.exit(1)

    # ── 인기순
    if args.popular:
        run_popular(
            channel_url=channel,
            cfg=cfg,
            api_key=api_key,
            top=args.top,
            skip_processed=not args.all_videos,
            mode=args.mode,
            llm=args.llm,
            gemini_model=args.gemini_model,
            claude_model=args.claude_model,
            fetch_only=args.fetch_only,
        )
        return

    # ── 모드 1: --latest
    if args.latest:
        run_latest(channel, cfg, api_key, mode=args.mode, llm=args.llm, gemini_model=args.gemini_model, claude_model=args.claude_model, fetch_only=args.fetch_only)
        return

    # ── 모드 3: --keyword
    if args.keyword:
        run_keyword(
            channel_url=channel,
            keyword=args.keyword,
            cfg=cfg,
            api_key=api_key,
            start_date=args.start,
            end_date=args.end or today,
            skip_processed=not args.all_videos,
            mode=args.mode,
            llm=args.llm,
            gemini_model=args.gemini_model,
            claude_model=args.claude_model,
            fetch_only=args.fetch_only,
        )
        return

    # ── 모드 2 / 4: 날짜 범위
    start = args.start or cfg['youtube'].get('date_range', {}).get('start')
    end = args.end or cfg['youtube'].get('date_range', {}).get('end') or today
    if not start:
        print("오류: --start 날짜를 지정하세요.")
        sys.exit(1)

    run_range(
        channel_url=channel,
        start_date=start,
        end_date=end,
        cfg=cfg,
        api_key=api_key,
        skip_processed=not args.all_videos,
        mode=args.mode,
        llm=args.llm,
        gemini_model=args.gemini_model,
        claude_model=args.claude_model,
        fetch_only=args.fetch_only,
    )


if __name__ == '__main__':
    main()
