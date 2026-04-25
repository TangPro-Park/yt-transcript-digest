import os
import re
import json
import logging

logger = logging.getLogger(__name__)


_WINDOWS_RESERVED = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10)),
}


def sanitize_dirname(name):
    cleaned = re.sub(r'[<>:"/\\|?*]', '_', name).strip().rstrip('. ')
    if not cleaned:
        return '_'
    if cleaned.upper() in _WINDOWS_RESERVED:
        cleaned = f'_{cleaned}'
    return cleaned


def title_to_slug(title, max_len=60):
    slug = re.sub(r'[^\w\s가-힣]', '', title)
    slug = re.sub(r'\s+', '_', slug.strip())
    return slug[:max_len]


def save_markdown(content, channel_name, date, title, base_dir='./output', prefix='', subdir=''):
    channel_dir = os.path.join(base_dir, sanitize_dirname(channel_name))
    if subdir:
        channel_dir = os.path.join(channel_dir, subdir)
    os.makedirs(channel_dir, exist_ok=True)

    filename = f"{prefix}{date}_{title_to_slug(title)}.md"
    filepath = os.path.join(channel_dir, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    logger.info(f"저장: {filepath}")
    return filepath


def load_processed(channel_dir):
    path = os.path.join(channel_dir, '.processed.json')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return set(json.load(f))
    return set()


def mark_processed(video_id, channel_dir):
    os.makedirs(channel_dir, exist_ok=True)
    processed = load_processed(channel_dir)
    processed.add(video_id)
    path = os.path.join(channel_dir, '.processed.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(sorted(processed), f, ensure_ascii=False, indent=2)


def generate_index(channel_name, base_dir='./output'):
    channel_dir = os.path.join(base_dir, sanitize_dirname(channel_name))
    if not os.path.exists(channel_dir):
        return None

    md_files = sorted(
        [f for f in os.listdir(channel_dir) if f.endswith('.md') and f != 'INDEX.md'],
        reverse=True,
    )

    lines = [
        f"# {channel_name} — 영상 분석 인덱스\n\n",
        f"총 **{len(md_files)}편**\n\n",
        "| 날짜 | 제목 |\n",
        "|------|------|\n",
    ]
    for fname in md_files:
        m = re.match(r'(\d{4}-\d{2}-\d{2}|unknown-date)_(.*?)\.md$', fname)
        if m:
            date, slug = m.groups()
            title = slug.replace('_', ' ')
            lines.append(f"| {date} | [{title}]({fname}) |\n")

    index_path = os.path.join(channel_dir, 'INDEX.md')
    with open(index_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)

    logger.info(f"인덱스 생성: {index_path}")
    return index_path
