from __future__ import annotations

import hmac
import json
import os
import secrets
import tempfile
import time
from html import escape
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response


DEFAULT_AUTH_PASSWORD_PATH = "./secrets/palate-auth-password"
DEFAULT_AUTH_STATE_PATH = "./secrets/palate-oauth.json"
DEFAULT_AUTH_SCOPE = "palate.access"
DEFAULT_ACCESS_TOKEN_SECONDS = 3600
DEFAULT_REFRESH_TOKEN_SECONDS = 60 * 60 * 24 * 30
AUTH_REQUEST_SECONDS = 10 * 60
AUTH_CODE_SECONDS = 5 * 60


def auth_enabled() -> bool:
    return os.getenv("PALATE_AUTH_ENABLED", "0").lower() in {"1", "true", "yes"}


def oauth_scopes() -> list[str]:
    configured = os.getenv("PALATE_AUTH_SCOPES", DEFAULT_AUTH_SCOPE)
    return [scope for scope in configured.split() if scope]


def auth_password_path() -> Path:
    return Path(
        os.getenv("PALATE_AUTH_PASSWORD_FILE", DEFAULT_AUTH_PASSWORD_PATH)
    ).expanduser()


def auth_state_path() -> Path:
    return Path(os.getenv("PALATE_AUTH_STATE_PATH", DEFAULT_AUTH_STATE_PATH)).expanduser()


def public_base_url() -> str:
    configured = os.getenv("PALATE_PUBLIC_BASE_URL")
    if not configured:
        raise RuntimeError(
            "PALATE_PUBLIC_BASE_URL is required when PALATE_AUTH_ENABLED=1."
        )
    return configured.rstrip("/")


def ensure_auth_password() -> str:
    configured = os.getenv("PALATE_AUTH_PASSWORD")
    if configured:
        return configured

    path = auth_password_path()
    if path.exists():
        return path.read_text(encoding="utf-8").strip()

    path.parent.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(24)
    path.write_text(password + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return password


def build_auth_components() -> tuple[AuthSettings | None, "PalateOAuthProvider | None"]:
    if not auth_enabled():
        return None, None

    base_url = public_base_url()
    scopes = oauth_scopes()
    provider = PalateOAuthProvider(
        issuer_url=base_url,
        password=ensure_auth_password(),
        state_path=auth_state_path(),
        scopes=scopes,
        access_token_seconds=int(
            os.getenv("PALATE_AUTH_ACCESS_TOKEN_SECONDS", DEFAULT_ACCESS_TOKEN_SECONDS)
        ),
        refresh_token_seconds=int(
            os.getenv("PALATE_AUTH_REFRESH_TOKEN_SECONDS", DEFAULT_REFRESH_TOKEN_SECONDS)
        ),
    )
    auth_settings = AuthSettings(
        issuer_url=AnyHttpUrl(base_url),
        resource_server_url=AnyHttpUrl(f"{base_url}/mcp"),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=scopes,
            default_scopes=scopes,
        ),
        required_scopes=scopes,
    )
    return auth_settings, provider


class PalateOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    def __init__(
        self,
        *,
        issuer_url: str,
        password: str,
        state_path: Path,
        scopes: list[str],
        access_token_seconds: int = DEFAULT_ACCESS_TOKEN_SECONDS,
        refresh_token_seconds: int = DEFAULT_REFRESH_TOKEN_SECONDS,
    ):
        self.issuer_url = issuer_url.rstrip("/")
        self.password = password
        self.state_path = state_path
        self.scopes = scopes
        self.access_token_seconds = access_token_seconds
        self.refresh_token_seconds = refresh_token_seconds
        self._lock = RLock()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._save_state(self._load_state())

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with self._lock:
            client = self._load_state()["clients"].get(client_id)
        if not client:
            return None
        return OAuthClientInformationFull.model_validate(client)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id:
            raise ValueError("client_id is required")

        with self._lock:
            state = self._load_state()
            state["clients"][client_info.client_id] = dump_model(client_info)
            self._save_state(state)

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        if not client.client_id:
            raise ValueError("client_id is required")

        request_id = secrets.token_urlsafe(32)
        pending = {
            "client_id": client.client_id,
            "state": params.state,
            "scopes": params.scopes or self.scopes,
            "code_challenge": params.code_challenge,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "resource": params.resource,
            "expires_at": int(time.time()) + AUTH_REQUEST_SECONDS,
        }
        with self._lock:
            state = self._load_state()
            state["pending_authorizations"][request_id] = pending
            self._prune_expired(state)
            self._save_state(state)

        return f"{self.issuer_url}/palate-auth?{urlencode({'request_id': request_id})}"

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        with self._lock:
            code = self._load_state()["authorization_codes"].get(authorization_code)
        if not code or code.get("client_id") != client.client_id:
            return None
        return AuthorizationCode.model_validate(code)

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        with self._lock:
            state = self._load_state()
            state["authorization_codes"].pop(authorization_code.code, None)
            token = self._issue_tokens(
                state,
                client_id=client.client_id or authorization_code.client_id,
                scopes=authorization_code.scopes,
                resource=authorization_code.resource,
            )
            self._save_state(state)
            return token

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        with self._lock:
            token = self._load_state()["refresh_tokens"].get(refresh_token)
        if not token or token.get("client_id") != client.client_id:
            return None
        return RefreshToken.model_validate(token)

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        if any(scope not in refresh_token.scopes for scope in scopes):
            raise TokenError("invalid_scope", "requested scope was not granted")

        with self._lock:
            state = self._load_state()
            state["refresh_tokens"].pop(refresh_token.token, None)
            token = self._issue_tokens(
                state,
                client_id=client.client_id or refresh_token.client_id,
                scopes=scopes or refresh_token.scopes,
                resource=None,
            )
            self._save_state(state)
            return token

    async def load_access_token(self, token: str) -> AccessToken | None:
        with self._lock:
            state = self._load_state()
            stored = state["access_tokens"].get(token)
            if stored and is_expired(stored):
                state["access_tokens"].pop(token, None)
                self._save_state(state)
                stored = None
        if not stored:
            return None
        return AccessToken.model_validate(stored)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        with self._lock:
            state = self._load_state()
            state["access_tokens"].pop(token.token, None)
            state["refresh_tokens"].pop(token.token, None)
            self._save_state(state)

    def complete_authorization(self, request_id: str, password: str) -> str | None:
        if not hmac.compare_digest(password, self.password):
            return None

        with self._lock:
            state = self._load_state()
            pending = state["pending_authorizations"].pop(request_id, None)
            if not pending or is_expired(pending):
                self._save_state(state)
                return None

            code_value = secrets.token_urlsafe(32)
            code = AuthorizationCode(
                code=code_value,
                scopes=pending["scopes"],
                expires_at=time.time() + AUTH_CODE_SECONDS,
                client_id=pending["client_id"],
                code_challenge=pending["code_challenge"],
                redirect_uri=pending["redirect_uri"],
                redirect_uri_provided_explicitly=pending[
                    "redirect_uri_provided_explicitly"
                ],
                resource=pending.get("resource"),
            )
            state["authorization_codes"][code_value] = dump_model(code)
            self._save_state(state)

        params = {"code": code_value}
        if pending.get("state"):
            params["state"] = pending["state"]
        return add_query_params(pending["redirect_uri"], params)

    def _issue_tokens(
        self,
        state: dict[str, Any],
        *,
        client_id: str,
        scopes: list[str],
        resource: str | None,
    ) -> OAuthToken:
        now = int(time.time())
        access_token_value = secrets.token_urlsafe(32)
        refresh_token_value = secrets.token_urlsafe(32)

        access_token = AccessToken(
            token=access_token_value,
            client_id=client_id,
            scopes=scopes,
            expires_at=now + self.access_token_seconds,
            resource=resource,
        )
        refresh_token = RefreshToken(
            token=refresh_token_value,
            client_id=client_id,
            scopes=scopes,
            expires_at=now + self.refresh_token_seconds,
        )

        state["access_tokens"][access_token_value] = dump_model(access_token)
        state["refresh_tokens"][refresh_token_value] = dump_model(refresh_token)

        return OAuthToken(
            access_token=access_token_value,
            token_type="Bearer",
            expires_in=self.access_token_seconds,
            refresh_token=refresh_token_value,
            scope=" ".join(scopes),
        )

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return empty_state()
        try:
            with self.state_path.open("r", encoding="utf-8") as file:
                state = json.load(file)
        except json.JSONDecodeError:
            state = empty_state()

        clean = empty_state()
        for key in clean:
            if isinstance(state.get(key), dict):
                clean[key] = state[key]
        return clean

    def _save_state(self, state: dict[str, Any]) -> None:
        self._prune_expired(state)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.state_path.parent,
            delete=False,
        ) as file:
            json.dump(state, file, indent=2, sort_keys=True)
            file.write("\n")
            temp_path = Path(file.name)
        temp_path.replace(self.state_path)
        try:
            self.state_path.chmod(0o600)
        except OSError:
            pass

    def _prune_expired(self, state: dict[str, Any]) -> None:
        for bucket_name in [
            "pending_authorizations",
            "authorization_codes",
            "access_tokens",
            "refresh_tokens",
        ]:
            bucket = state[bucket_name]
            for key, value in list(bucket.items()):
                if is_expired(value):
                    bucket.pop(key, None)


def register_auth_routes(mcp: FastMCP, provider: PalateOAuthProvider) -> None:
    @mcp.custom_route("/palate-auth", methods=["GET", "POST"], include_in_schema=False)
    async def palate_auth(request: Request) -> Response:
        if request.method == "GET":
            request_id = request.query_params.get("request_id", "")
            return auth_form(request_id=request_id)

        form = await request.form()
        request_id = str(form.get("request_id", ""))
        password = str(form.get("password", ""))
        redirect_url = provider.complete_authorization(request_id, password)
        if redirect_url:
            return RedirectResponse(redirect_url, status_code=302)
        return auth_form(request_id=request_id, error="Invalid or expired authorization.")

    issuer_metadata_path = authorization_server_well_known_path(provider)
    if issuer_metadata_path != "/.well-known/oauth-authorization-server":

        @mcp.custom_route(issuer_metadata_path, methods=["GET"], include_in_schema=False)
        async def palate_authorization_server_metadata(request: Request) -> Response:
            return JSONResponse(
                authorization_server_metadata(provider),
                headers={"Cache-Control": "public, max-age=3600"},
            )


def authorization_server_well_known_path(provider: PalateOAuthProvider) -> str:
    issuer_path = urlsplit(provider.issuer_url).path.strip("/")
    if not issuer_path:
        return "/.well-known/oauth-authorization-server"
    return f"/.well-known/oauth-authorization-server/{issuer_path}"


def authorization_server_metadata(provider: PalateOAuthProvider) -> dict[str, Any]:
    return {
        "issuer": provider.issuer_url,
        "authorization_endpoint": f"{provider.issuer_url}/authorize",
        "token_endpoint": f"{provider.issuer_url}/token",
        "registration_endpoint": f"{provider.issuer_url}/register",
        "scopes_supported": provider.scopes,
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": [
            "client_secret_post",
            "client_secret_basic",
        ],
        "code_challenge_methods_supported": ["S256"],
    }


def auth_form(request_id: str, error: str | None = None) -> HTMLResponse:
    safe_request_id = escape(request_id, quote=True)
    error_html = (
        f'<p class="error">{escape(error)}</p>'
        if error
        else ""
    )
    html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Authorize Palate</title>
    <style>
      body {{
        background: #101114;
        color: #f3f4f6;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
      }}
      main {{
        width: min(420px, calc(100vw - 40px));
      }}
      h1 {{
        font-size: 24px;
        margin: 0 0 8px;
      }}
      p {{
        color: #c9ccd2;
        line-height: 1.45;
      }}
      label {{
        display: block;
        font-size: 14px;
        margin: 24px 0 8px;
      }}
      input, button {{
        box-sizing: border-box;
        width: 100%;
        border-radius: 8px;
        border: 1px solid #3a3d45;
        font: inherit;
        padding: 12px 14px;
      }}
      input {{
        background: #191b20;
        color: #f3f4f6;
      }}
      button {{
        margin-top: 14px;
        background: #f3f4f6;
        color: #101114;
        cursor: pointer;
      }}
      .error {{
        color: #ffb4ab;
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>Authorize Palate</h1>
      <p>Enter the Palate auth password to connect this ChatGPT connector.</p>
      {error_html}
      <form method="post">
        <input type="hidden" name="request_id" value="{safe_request_id}">
        <label for="password">Password</label>
        <input id="password" name="password" type="password" autocomplete="current-password" autofocus>
        <button type="submit">Authorize</button>
      </form>
    </main>
  </body>
</html>"""
    return HTMLResponse(html, status_code=401 if error else 200)


def empty_state() -> dict[str, dict[str, Any]]:
    return {
        "clients": {},
        "pending_authorizations": {},
        "authorization_codes": {},
        "access_tokens": {},
        "refresh_tokens": {},
    }


def dump_model(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_none=True)


def is_expired(value: dict[str, Any]) -> bool:
    expires_at = value.get("expires_at")
    return expires_at is not None and float(expires_at) < time.time()


def add_query_params(url: str, params: dict[str, str]) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(params)
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )
