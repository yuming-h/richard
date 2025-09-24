from fastapi import FastAPI
from app.users.routes.auth_routes import router as auth_router
from app.users.routes.user_routes import router as user_router
import logging
from app.learning.routes import router as learning_router

app = FastAPI(title="Richard API", description="API for Richard App")

log = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO)
app.include_router(auth_router)
app.include_router(user_router)
app.include_router(learning_router)


@app.get("/")
async def read_root():
    return {"message": "Hello from richard-api!"}


def main():
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
