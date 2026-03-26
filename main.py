from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from app.api.routes import router
import os
import uvicorn
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="SH智能体平台", version="1.0.0", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom Docs with reliable CDN (unpkg)
@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_js_url="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui-bundle.js",
        swagger_css_url="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui.css",
    )

@app.get("/redoc", include_in_schema=False)
async def redoc_html():
    return get_redoc_html(
        openapi_url=app.openapi_url,
        title=app.title + " - ReDoc",
        redoc_js_url="https://unpkg.com/redoc@next/bundles/redoc.standalone.js",
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

@app.get("/history_page")
async def read_history():
    return FileResponse(os.path.join(FRONTEND_DIR, 'history.html'))

# Silence Vite HMR requests from dev environments
@app.get("/@vite/client", include_in_schema=False)
async def vite_client():
    return Response(content="", media_type="application/javascript")

if __name__ == "__main__":
    host = os.getenv("APP_HOST", "0.0.0.0")
    port = int(os.getenv("APP_PORT", os.getenv("PORT", "5000")))
    reload_enabled = os.getenv("APP_RELOAD", "true").lower() == "true"
    uvicorn.run(
        "main:app", 
        host=host, 
        port=port, 
        reload=reload_enabled,
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
