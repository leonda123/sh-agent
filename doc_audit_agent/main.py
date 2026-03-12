import uvicorn
import os
import sys
from dotenv import load_dotenv

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env file explicitly
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)
    print(f"Loaded .env from {env_path}")
else:
    print(f"Warning: .env file not found at {env_path}")

# FIX: Set dummy OPENAI_API_KEY to satisfy CrewAI's validation when using other providers
if "OPENAI_API_KEY" not in os.environ:
    os.environ["OPENAI_API_KEY"] = "NA"

# Set CrewAI storage directory to a local folder to avoid permission issues
os.environ["CREWAI_STORAGE_DIR"] = os.path.join(os.getcwd(), "doc_audit_agent", "storage")
os.makedirs(os.environ["CREWAI_STORAGE_DIR"], exist_ok=True)

if __name__ == "__main__":
    # Increased timeout_keep_alive to prevent disconnection during long processing
    # Also added reload_excludes to prevent server reload when output/upload/storage files change
    uvicorn.run(
        "doc_audit_agent.api.app:app", 
        host="0.0.0.0", 
        port=5000, 
        reload=True, 
        timeout_keep_alive=300,
        reload_excludes=["*/outputs/*", "*/uploads/*", "*/storage/*"]
    )
