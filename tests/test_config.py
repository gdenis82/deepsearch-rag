import os

from app.core.config import settings


def test_config_project_info():
    """Проверяет основные метаданные проекта."""
    assert settings.PROJECT_NAME == "DeepSearch"
    assert settings.API_V1_STR == "/api/v1"

def test_config_paths_absolute():
    """
    Проверяет логику __init__ в Settings:
    пути CHROMA_PATH и DOCUMENTS_PATH должны автоматически становиться абсолютными.
    """
    assert os.path.isabs(settings.CHROMA_PATH), "CHROMA_PATH должен быть абсолютным"
    assert os.path.isabs(settings.DOCUMENTS_PATH), "DOCUMENTS_PATH должен быть абсолютным"

def test_database_url_construction():
    """Проверяет, что DATABASE_URL собирается корректно из частей."""
    assert settings.DATABASE_URL is not None
    db_url = str(settings.DATABASE_URL)
    assert db_url.startswith("postgresql://")
    # Проверяем, что дефолтные или установленные юзер/порт попали в строку
    assert settings.POSTGRES_USER in db_url
    assert str(settings.POSTGRES_PORT) in db_url

def test_security_settings_present():
    """Проверяет наличие критических настроек безопасности."""
    # SECRET_KEY обязателен
    assert settings.SECRET_KEY
    assert settings.ALGORITHM
    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES > 0
