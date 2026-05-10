"""
Configuration management via pydantic-settings.
All values read from environment variables / .env file.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- MongoDB ---
    mongodb_uri: str = Field(..., description="MongoDB connection URI (same as Next.js MONGODB_URI)")
    # Mongoose defaults to 'test' when no DB is in the URI path.
    # Override this if your Atlas cluster uses a different database name.
    mongodb_db_name: str = Field(default="test", description="MongoDB database name")

    # --- Server ---
    mcp_server_port: int = Field(default=8001, description="Port this MCP server listens on")

    # --- CORS ---
    cors_origins: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:3000", "http://localhost:8000"],
        description="Allowed CORS origins (agents-server + chat client + Next.js app)",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_file_encoding="utf-8",
    )


settings = Settings()
