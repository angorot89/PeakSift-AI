"""Security headers on every API response (pure ASGI: streaming responses are untouched).

The API serves JSON and private media, never pages, so its policy is the strictest
possible: nothing may run, load or frame. Responses are user-specific, so they are
``no-store`` unless an endpoint says otherwise (media already does). HTTPS is mandatory in
production, so HSTS is sent there.
"""

BASE_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'; sandbox"),
    (b"cross-origin-resource-policy", b"same-site"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    (b"cache-control", b"no-store"),
)
HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")


class SecurityHeadersMiddleware:
    def __init__(self, app, *, hsts: bool = False) -> None:
        self.app = app
        self.headers = BASE_HEADERS + ((HSTS,) if hsts else ())

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                present = {name.lower() for name, _ in message.get("headers", [])}
                message["headers"] = [
                    *message.get("headers", []),
                    *((name, value) for name, value in self.headers if name not in present),
                ]
            await send(message)

        await self.app(scope, receive, send_with_headers)
