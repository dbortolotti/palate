from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull

from palate.oauth import (
    PalateOAuthProvider,
    authorization_server_metadata,
    authorization_server_well_known_path,
    build_auth_components,
)


class PalateOAuthProviderTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="palate-oauth-"))
        self.provider = PalateOAuthProvider(
            issuer_url="https://palate.example",
            password="correct horse",
            state_path=self.temp_dir / "oauth.json",
            scopes=["palate.access"],
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_authorization_requires_password_and_issues_tokens(self) -> None:
        client = OAuthClientInformationFull(
            client_id="client-1",
            client_secret="secret",
            redirect_uris=["https://chatgpt.example/callback"],
            token_endpoint_auth_method="client_secret_post",
        )
        await self.provider.register_client(client)

        redirect_to_login = await self.provider.authorize(
            client,
            AuthorizationParams(
                state="state-1",
                scopes=["palate.access"],
                code_challenge="challenge",
                redirect_uri="https://chatgpt.example/callback",
                redirect_uri_provided_explicitly=True,
                resource="https://palate.example/mcp",
            ),
        )
        request_id = parse_qs(urlsplit(redirect_to_login).query)["request_id"][0]

        self.assertIsNone(
            self.provider.complete_authorization(request_id, "wrong password")
        )
        callback_url = self.provider.complete_authorization(request_id, "correct horse")

        self.assertIsNotNone(callback_url)
        callback_query = parse_qs(urlsplit(callback_url or "").query)
        self.assertEqual(callback_query["state"], ["state-1"])
        authorization_code = callback_query["code"][0]

        loaded_code = await self.provider.load_authorization_code(
            client,
            authorization_code,
        )
        self.assertIsNotNone(loaded_code)

        token = await self.provider.exchange_authorization_code(client, loaded_code)
        self.assertEqual(token.token_type, "Bearer")
        self.assertEqual(token.scope, "palate.access")

        access_token = await self.provider.load_access_token(token.access_token)
        self.assertIsNotNone(access_token)
        self.assertEqual(access_token.client_id, "client-1")
        self.assertEqual(access_token.scopes, ["palate.access"])

        self.assertIsNone(
            await self.provider.load_authorization_code(client, authorization_code)
        )

    async def test_refresh_token_rotation(self) -> None:
        state = self.provider._load_state()
        token = self.provider._issue_tokens(
            state,
            client_id="client-1",
            scopes=["palate.access"],
            resource=None,
        )
        self.provider._save_state(state)
        refresh = await self.provider.load_refresh_token(
            OAuthClientInformationFull(
                client_id="client-1",
                redirect_uris=["https://chatgpt.example/callback"],
            ),
            token.refresh_token,
        )

        self.assertIsNotNone(refresh)
        refreshed = await self.provider.exchange_refresh_token(
            OAuthClientInformationFull(
                client_id="client-1",
                redirect_uris=["https://chatgpt.example/callback"],
            ),
            refresh,
            ["palate.access"],
        )

        self.assertNotEqual(refreshed.access_token, token.access_token)
        self.assertNotEqual(refreshed.refresh_token, token.refresh_token)

    def test_authorization_server_metadata_advertises_registration(self) -> None:
        provider = PalateOAuthProvider(
            issuer_url="https://palate.example/palate",
            password="correct horse",
            state_path=self.temp_dir / "path-oauth.json",
            scopes=["palate.access"],
        )

        self.assertEqual(
            authorization_server_well_known_path(provider),
            "/.well-known/oauth-authorization-server/palate",
        )
        self.assertEqual(
            authorization_server_metadata(provider)["registration_endpoint"],
            "https://palate.example/palate/register",
        )


class PalateOAuthConfigTest(unittest.TestCase):
    def test_build_auth_components_uses_public_base_url_and_password_file(self) -> None:
        temp_dir = Path(tempfile.mkdtemp(prefix="palate-oauth-config-"))
        try:
            password_path = temp_dir / "password"
            state_path = temp_dir / "oauth.json"
            with patch.dict(
                "os.environ",
                {
                    "PALATE_AUTH_ENABLED": "1",
                    "PALATE_PUBLIC_BASE_URL": "https://palate.example/",
                    "PALATE_AUTH_PASSWORD_FILE": str(password_path),
                    "PALATE_AUTH_STATE_PATH": str(state_path),
                    "PALATE_AUTH_SCOPES": "palate.access",
                },
                clear=True,
            ):
                settings, provider = build_auth_components()

            self.assertIsNotNone(settings)
            self.assertIsNotNone(provider)
            self.assertEqual(str(settings.issuer_url), "https://palate.example/")
            self.assertEqual(
                str(settings.resource_server_url),
                "https://palate.example/mcp",
            )
            self.assertEqual(settings.required_scopes, ["palate.access"])
            self.assertTrue(password_path.exists())
            self.assertTrue(state_path.exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
