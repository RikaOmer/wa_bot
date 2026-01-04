"""Google OAuth2 helpers for the Photos Library API."""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlencode

import httpx

from .models import TokenResponse

logger = logging.getLogger(__name__)

# Google Photos Library API scopes
# Note: photoslibrary.sharing was removed - Google deprecated the albums.share API
SCOPES = [
    "https://www.googleapis.com/auth/photoslibrary",
    "https://www.googleapis.com/auth/photoslibrary.appendonly",
]


class GoogleOAuth:
    """Handles Google OAuth2 flow for Photos Library API."""

    AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def generate_auth_url(self, state: str) -> str:
        """
        Generate the OAuth2 authorization URL.

        Args:
            state: A state parameter to maintain state between request and callback.
                   This should encode the group_jid to associate the token with the group.

        Returns:
            The authorization URL to redirect the user to.
        """
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",  # Get refresh token
            "prompt": "consent",  # Always show consent screen to get refresh token
            "state": state,
        }
        return f"{self.AUTHORIZATION_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> TokenResponse:
        """
        Exchange authorization code for access and refresh tokens.

        Args:
            code: The authorization code from the OAuth callback.

        Returns:
            TokenResponse with access_token, refresh_token, and expires_in.

        Raises:
            httpx.HTTPStatusError: If the token request fails.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.redirect_uri,
                },
            )
            response.raise_for_status()
            return TokenResponse.model_validate(response.json())

    async def refresh_access_token(self, refresh_token: str) -> TokenResponse:
        """
        Refresh an expired access token using the refresh token.

        Args:
            refresh_token: The refresh token from the initial authorization.

        Returns:
            TokenResponse with new access_token and expires_in.
            Note: refresh_token may not be returned if not rotated.

        Raises:
            httpx.HTTPStatusError: If the refresh request fails.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
            data = response.json()
            # Refresh token may not be in response, use existing one
            if "refresh_token" not in data:
                data["refresh_token"] = refresh_token
            return TokenResponse.model_validate(data)

    @staticmethod
    def calculate_expiry(expires_in: int) -> datetime:
        """
        Calculate the token expiry datetime from expires_in seconds.

        Args:
            expires_in: Seconds until the token expires.

        Returns:
            Datetime when the token will expire.
        """
        return datetime.now(timezone.utc) + timedelta(seconds=expires_in)

