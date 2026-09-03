"""Persistent JSON-lines client for the JHOC supervisor endpoint."""

from __future__ import annotations

import json
import socket
from threading import Event
import time
from typing import Any, Callable, Mapping


ProviderFunction = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class JHOCProviderClient:
    """Keep one provider connection alive and reconnect on transport loss."""

    def __init__(
        self,
        provider_id: str,
        handler: ProviderFunction,
        *,
        host: str = "127.0.0.1",
        port: int = 8766,
        reconnect_delay: float = 0.5,
        connect_timeout: float = 5.0,
    ) -> None:
        if not provider_id.strip() or not callable(handler):
            raise ValueError("provider_id and callable handler are required")
        if reconnect_delay <= 0 or connect_timeout <= 0:
            raise ValueError("connection delays must be positive")
        self.provider_id, self.handler = provider_id.strip(), handler
        self.host, self.port = host, port
        self.reconnect_delay, self.connect_timeout = reconnect_delay, connect_timeout
        self._stop = Event()
        self._socket: socket.socket | None = None

    def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                self._serve_connection()
            except (OSError, ValueError, json.JSONDecodeError):
                self._close_socket()
                self._stop.wait(self.reconnect_delay)

    def stop(self) -> None:
        self._stop.set()
        self._close_socket()

    def _serve_connection(self) -> None:
        connection = socket.create_connection((self.host, self.port), timeout=self.connect_timeout)
        connection.settimeout(None)
        self._socket = connection
        reader = connection.makefile("rb")
        writer = connection.makefile("wb")
        try:
            writer.write((json.dumps({"op": "register", "provider_id": self.provider_id}) + "\n").encode())
            writer.flush()
            registered = json.loads(reader.readline().decode("utf-8"))
            if not registered.get("ok"):
                raise ValueError("JHOC provider registration rejected")
            while not self._stop.is_set():
                line = reader.readline()
                if not line:
                    raise ConnectionError("JHOC supervisor disconnected")
                request = json.loads(line.decode("utf-8"))
                if request.get("op") != "request":
                    continue
                try:
                    payload = self.handler(request.get("payload", {}))
                    if not isinstance(payload, Mapping):
                        raise TypeError("provider handler must return a mapping")
                    reply = {"correlation_id": request.get("correlation_id"), "payload": dict(payload)}
                except Exception as error:
                    reply = {
                        "correlation_id": request.get("correlation_id"),
                        "payload": {"error": f"{type(error).__name__}: {error}"},
                    }
                writer.write((json.dumps(reply, sort_keys=True) + "\n").encode("utf-8"))
                writer.flush()
        finally:
            reader.close()
            writer.close()
            self._close_socket()

    def _close_socket(self) -> None:
        connection, self._socket = self._socket, None
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()


__all__ = ["JHOCProviderClient", "ProviderFunction"]
