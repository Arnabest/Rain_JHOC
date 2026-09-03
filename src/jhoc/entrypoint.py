"""The single supported JHOC application construction entrypoint."""

from __future__ import annotations

from .application import ApplicationConfig, JHOCApplication


def create_application(config: ApplicationConfig | None = None) -> JHOCApplication:
    return JHOCApplication(config)


__all__ = ["create_application"]
