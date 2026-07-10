from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.chatRoutes import router as chatRoutes

app = FastAPI(
    title = "Agent Application",
    description = "Backend API for Agent Application",
    version = "1.0.0",
    redirect_slashes=False,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins = ["*"],
    allow_credentials = True,
    allow_methods = ["*"],
    allow_headers = ["*"],
)

app.include_router(chatRoutes, prefix="/api/chats")

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app,host="0.0.0.0",port = 8000, reload=True)
