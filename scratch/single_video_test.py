import logging
import yaml
import sys
import os

# Add root directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.transcript import fetch_transcript
from src.llm_processor import process_with_local_llm
from src.storage import save_raw_transcript, save_markdown_result, format_filename, append_to_index

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_single_video_test(video_id: str):
    # Load config
    with open('config.yaml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    languages = config.get("youtube", {}).get("languages", ["ko", "en"])
    
    print(f"\n--- Starting Single Video Test: {video_id} ---")
    
    # 1. Fetch Transcript
    print(f"[1/3] Fetching transcript for {video_id}...")
    transcript_text = fetch_transcript(video_id, languages)
    if not transcript_text:
        print("FAILED: Could not fetch transcript.")
        return
    
    save_raw_transcript(video_id, transcript_text)
    
    # 2. Process with LLM
    print(f"[2/3] Processing with Local LLM (Gemma 4)... This may take a moment.")
    try:
        md_content = process_with_local_llm(transcript_text, config)
        
        # 3. Save Result
        # For test, we use a placeholder title/channel
        video_data = {
            'video_id': video_id,
            'title': '클로드_디자인_피바람_단일_영상_테스트',
            'published_at': '2026-04-22T00:00:00Z'
        }
        channel_name = "Single_Test"
        filename = format_filename(config, video_data)
        
        print(f"[3/3] Saving result to output/{channel_name}/{filename}...")
        save_markdown_result(channel_name, filename, md_content, config)
        append_to_index(channel_name, video_data, filename, config)
        
        print("\n--- Test Completed Successfully! ---")
        print(f"Check the result here: output/{channel_name}/{filename}")
        
    except Exception as e:
        print(f"FAILED: LLM processing error - {e}")

if __name__ == "__main__":
    VIDEO_ID = "P9LSUz_08g0"
    run_single_video_test(VIDEO_ID)
