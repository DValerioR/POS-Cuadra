from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+psycopg://usuario:password@localhost:5432/pos"
    # Cuánto dura una sesión desde que se inicia (aprox. un turno).
    horas_sesion: int = 12
    # Solo True si el servidor se sirve por HTTPS; en la red local es HTTP.
    cookie_segura: bool = False
    # Para mostrar fechas (tickets, reportes); en la base todo se guarda en UTC.
    zona_horaria: str = "America/Mexico_City"


settings = Settings()
