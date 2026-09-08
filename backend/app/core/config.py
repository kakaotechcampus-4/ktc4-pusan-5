from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "BASIS API"
    cors_origins: list[str] = ["http://localhost:5173"]

    dart_api_key: str = ""
    ecos_api_key: str = ""


settings = Settings()
