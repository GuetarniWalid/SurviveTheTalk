"""FastAPI endpoint for spawning voice bot into a LiveKit room."""

import subprocess
import sys
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pipecat.runner.livekit import generate_token, generate_token_with_agent

from config import Settings

app = FastAPI(title="SurviveTheTalk API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings = Settings()


@app.post("/connect")
async def connect() -> dict:
    """Create a LiveKit room and spawn a voice bot into it.

    Returns room name, user token, and LiveKit URL for the client to connect.
    """
    room_name = f"room-{uuid4()}"

    agent_token = generate_token_with_agent(
        room_name=room_name,
        participant_name="marcus-bot",
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )

    subprocess.Popen(
        [
            sys.executable,
            "-m",
            "pipeline.bot",
            "--url",
            settings.livekit_url,
            "--room",
            room_name,
            "--token",
            agent_token,
        ],
    )
    logger.info(f"Spawned bot for room {room_name}")

    user_token = generate_token(
        room_name=room_name,
        participant_name="user",
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )

    return {
        "room_name": room_name,
        "token": user_token,
        "livekit_url": settings.livekit_url,
    }
