"""
app/middleware.py
-------------------
A pure-ASGI middleware that rejects oversized request bodies for a
specific set of paths, checked as the body streams in — so it protects
against a client that omits or lies about the `Content-Length` header,
not just against a truthful one.

This implements the "tamaño máximo HTTP antes incluso de tokenizar"
protection: the body is measured and rejected (413) before it is ever
handed to FastAPI's request parsing, Pydantic validation, or the LLM
prompt itself.

Applied narrowly (only to the given `paths`) so it never affects any
other endpoint in the API (e.g. the booking endpoints keep their own,
separate limits).
"""
from __future__ import annotations


class _BodyTooLarge(Exception):
    pass


class MaxBodySizeMiddleware:
    def __init__(self, app, max_bytes: int, paths: set[str]):
        self.app = app
        self.max_bytes = max_bytes
        self.paths = paths

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] not in self.paths:
            await self.app(scope, receive, send)
            return

        # Fast path: if the client is honest about Content-Length and it's
        # already too big, reject without reading any body bytes at all.
        headers = dict(scope.get("headers") or [])
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    await self._send_413(send, self.max_bytes)
                    return
            except ValueError:
                pass  # malformed header; fall through to the streaming check below

        total = 0
        response_started = False

        async def guarded_receive():
            nonlocal total
            message = await receive()
            if message.get("type") == "http.request":
                total += len(message.get("body") or b"")
                if total > self.max_bytes:
                    raise _BodyTooLarge()
            return message

        async def tracking_send(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, guarded_receive, tracking_send)
        except _BodyTooLarge:
            # Only safe to send our own response if the downstream app
            # hasn't already started sending one.
            if not response_started:
                await self._send_413(send, self.max_bytes)

    @staticmethod
    async def _send_413(send, max_bytes: int) -> None:
        body = f'{{"detail":"Request body too large (max {max_bytes} bytes)."}}'.encode()
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})
