"""Configuration management for Morpheus."""

import os
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Discord Bot Configuration
    discord_bot_token: str
    discord_approval_channel_id: int = 1472808626073632880
    discord_log_channel_id: int = 1472795210139308194
    discord_approver_id: int = 404340348194652160
    
    # API Configuration
    morpheus_api_key: str
    
    # Vaultwarden Configuration
    vaultwarden_url: str = "https://vault.pranavprem.com"
    vaultwarden_master_password: str
    
    # Security Configuration
    approval_timeout_seconds: int = 600
    
    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()