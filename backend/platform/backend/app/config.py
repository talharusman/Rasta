from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = ''
    supabase_url: str = ''
    supabase_publishable_key: str = ''
    supabase_jwt_audience: str = 'authenticated'
    supabase_jwt_algorithm: str = 'ES256'
    cors_origins: list[str] = ['http://localhost:5173']
    internal_api_key: str = ''
    ai_base_url: str = ''
    ai_api_key: str = ''
    upload_dir: str = 'uploads'

settings = Settings()
