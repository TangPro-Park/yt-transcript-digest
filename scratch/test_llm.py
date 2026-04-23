import yaml
import os
from openai import OpenAI

def test_ollama_connection():
    # Load config to get the same settings as the main app
    with open('config.yaml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    llm_config = config.get("local_llm", {})
    base_url = llm_config.get("base_url", "http://localhost:11434/v1")
    model = llm_config.get("model", "gemma4:e4b")
    
    print(f"Testing connection to {base_url} with model {model}...")
    
    try:
        client = OpenAI(
            base_url=base_url,
            api_key="local-dummy-key"
        )
        
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": "안녕하세요! 간단하게 자기소개 부탁드려요."}
            ],
            temperature=0.1,
            max_tokens=100
        )
        
        print("\n--- LLM Response ---")
        print(response.choices[0].message.content)
        print("--------------------\n")
        print("Connection Test: SUCCESS")
        
    except Exception as e:
        print(f"Connection Test: FAILED - {str(e)}")

if __name__ == "__main__":
    test_ollama_connection()
