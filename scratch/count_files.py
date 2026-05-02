import os, glob

# 깃 트래킹 파일 수
tracked_output = open('scratch/tracked_output.txt', encoding='utf-8').read().splitlines()
tracked_output = [l for l in tracked_output if l.strip()]

# 실제 디스크 파일 수
disk_output_md = glob.glob('output/**/*.md', recursive=True)
disk_output_all = glob.glob('output/**/*', recursive=True)
disk_output_all = [f for f in disk_output_all if os.path.isfile(f)]

disk_transcript_txt = glob.glob('cache/transcripts/*.txt')
disk_transcript_json = glob.glob('cache/transcripts/*.json')

print(f"=== output/ ===")
print(f"  깃 트래킹: {len(tracked_output)}개 파일")
print(f"  디스크 전체: {len(disk_output_all)}개 파일")
print(f"  디스크 .md만: {len(disk_output_md)}개")
print(f"\n=== cache/transcripts/ ===")
print(f"  디스크 .txt: {len(disk_transcript_txt)}개 (트랜스크립트)")
print(f"  디스크 .json: {len(disk_transcript_json)}개 (메타데이터)")

# .gitignore에 cache가 있는지 확인
gi = open('.gitignore', encoding='utf-8').read() if os.path.exists('.gitignore') else ''
print(f"\n=== .gitignore ===")
cache_ignored = 'cache/' in gi or 'cache' in gi
print(f"  cache/ 무시 여부: {'YES' if cache_ignored else 'NO'}")
print(f"  output/ 무시 여부: {'YES' if 'output/' in gi or 'output' in gi else 'NO'}")
