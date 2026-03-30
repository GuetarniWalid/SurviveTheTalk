from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    soniox_api_key: str
    openrouter_api_key: str
    cartesia_api_key: str
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    jwt_secret: str = ""
    resend_api_key: str = ""
    database_path: str = "/opt/survive-the-talk/data/db.sqlite"

    model_config = {"env_file": ".env"}
