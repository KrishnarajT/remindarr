from fastapi import FastAPI
from .routes import notifications, ui
from .database import engine, Base

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Remindarr")

# Include routers
app.include_router(notifications.router)
app.include_router(ui.router)

@app.get("/")
async def root():
    return {"message": "Welcome to Remindarr!"}