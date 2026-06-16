from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from starlette._exception_handler import (
    ExceptionHandlers,
    StatusHandlers,
    wrap_app_handling_exceptions,
)
from starlette.exceptions import HTTPException, WebSocketException
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, Response
from starlette.types import ASGIApp, ExceptionHandler, Receive, Scope, Send
from starlette.websockets import WebSocket


class ExceptionMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        handlers: Mapping[Any, ExceptionHandler] | None = None,
        debug: bool = False,
    ) -> None:
        self.app = app
        self.debug = debug
        self._status_handlers: StatusHandlers = {}
        self._exception_handlers: ExceptionHandlers = {
            HTTPException: self.http_exception,
            WebSocketException: self.websocket_exception,
        }
        if handlers is not None:  # pragma: no branch
            for key, value in handlers.items():
                self.add_exception_handler(key, value)

    def add_exception_handler(
        self,
        exc_class_or_status_code: int | type[Exception],
        handler: ExceptionHandler,
    ) -> None:
        if isinstance(exc_class_or_status_code, int):
            self._status_handlers[exc_class_or_status_code] = handler
        else:
            assert issubclass(exc_class_or_status_code, Exception)
            self._exception_handlers[exc_class_or_status_code] = handler

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        scope["starlette.exception_handlers"] = (
            self._exception_handlers,
            self._status_handlers,
        )

        conn: Request | WebSocket
        if scope["type"] == "http":
            conn = Request(scope, receive, send)
        else:
            conn = WebSocket(scope, receive, send)

        await wrap_app_handling_exceptions(self.app, conn)(scope, receive, send)

    async def http_exception(self, request: Request, exc: Exception) -> Response:
        assert isinstance(exc, HTTPException)
        if exc.status_code in {204, 304}:
            return Response(status_code=exc.status_code, headers=exc.headers)
        if self.debug:
            accept = request.headers.get("accept", "")
            if "text/html" in accept:
                return self.debug_http_response_html(exc)
            return self.debug_http_response_plain(exc)
        return PlainTextResponse(exc.detail, status_code=exc.status_code, headers=exc.headers)

    def debug_http_response_html(self, exc: HTTPException) -> Response:
        html = f"""
        <html>
            <head>
                <style type='text/css'>
                    p {{
                        color: #211c1c;
                    }}
                    .error-container {{
                        border: 1px solid #038BB8;
                    }}
                    .error-title {{
                        background-color: #038BB8;
                        color: lemonchiffon;
                        padding: 12px;
                        font-size: 20px;
                        margin-top: 0px;
                    }}
                    .error-details {{
                        padding: 15px;
                    }}
                </style>
                <title>Starlette Debugger</title>
            </head>
            <body>
                <h1>{exc.status_code} Error</h1>
                <h2>{exc.detail}</h2>
                <div class="error-container">
                    <p class="error-title">Exception</p>
                    <div class="error-details">
                        <p><b>status_code:</b> {exc.status_code}</p>
                        <p><b>detail:</b> {exc.detail}</p>
                        {f'<p><b>headers:</b> {dict(exc.headers)}</p>' if exc.headers else ''}
                    </div>
                </div>
            </body>
        </html>
        """
        return HTMLResponse(html, status_code=exc.status_code, headers=exc.headers)

    def debug_http_response_plain(self, exc: HTTPException) -> Response:
        text = f"{exc.status_code} {exc.detail}\n\n"
        if exc.headers:
            text += "Headers:\n"
            for key, value in exc.headers.items():
                text += f"  {key}: {value}\n"
        return PlainTextResponse(text, status_code=exc.status_code, headers=exc.headers)

    async def websocket_exception(self, websocket: WebSocket, exc: Exception) -> None:
        assert isinstance(exc, WebSocketException)
        await websocket.close(code=exc.code, reason=exc.reason)  # pragma: no cover
