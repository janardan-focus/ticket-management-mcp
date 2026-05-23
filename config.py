"""
Configuration management via pydantic-settings.
All values read from environment variables / .env file.

Migration note: MongoDB settings have been removed. The MCP server now calls
the Next.js REST API instead of talking to MongoDB directly.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Next.js REST API ---
    tms_api_base_url: str = Field(
        default="http://localhost:3000",
        description="Base URL of the Next.js Ticket Management System API",
    )

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
