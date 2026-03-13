from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from app.api.routes import router
import os
import uvicorn

app = FastAPI(title="SH Agent Platform", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Base Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)

app.include_router(router, prefix="/api")

# Mount frontend
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/")
def read_root():
    return FileResponse(os.path.join(FRONTEND_DIR, 'index.html'))

@app.get("/ui")
async def read_index():
    return FileResponse(os.path.join(FRONTEND_DIR, 'index.html'))

# Silence Vite HMR requests from dev environments
@app.get("/@vite/client", include_in_schema=False)
async def vite_client():
    return Response(content="", media_type="application/javascript")

if __name__ == "__main__":
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=5000, 
        reload=True,
        reload_excludes=[
            "outputs", 
            "uploads", 
            "storage", 
            "logs", 
            "outputs/*", 
            "uploads/*", 
            "storage/*", 
            "logs/*", 
            "*.log", 
            "**/*.log"
        ]
    )
