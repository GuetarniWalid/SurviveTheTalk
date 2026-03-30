"""SurviveTheTalk server — launches the FastAPI application."""

import uvicorn
from loguru import logger


def main() -> None:
    logger.info("Starting SurviveTheTalk server")
    uvicorn.run("api.call_endpoint:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
