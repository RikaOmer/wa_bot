"""Handler for trip album setup and photo upload."""

import base64
import json
import logging
from typing import Optional

import httpx
from sqlmodel.ext.asyncio.session import AsyncSession
from voyageai.client_async import AsyncClient

from config import Settings
from google_photos import GoogleOAuth, GooglePhotosClient
from models import Message, TripAlbum
from models.upsert import upsert
from whatsapp import WhatsAppClient
from .base_handler import BaseHandler

logger = logging.getLogger(__name__)


def encode_state(data: dict) -> str:
    """Encode a dict to a base64 state parameter."""
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()


class TripAlbumHandler(BaseHandler):
    """Handles trip album setup and photo uploads."""

    def __init__(
        self,
        session: AsyncSession,
        whatsapp: WhatsAppClient,
        embedding_client: AsyncClient,
        settings: Settings,
    ):
        super().__init__(session, whatsapp, embedding_client)
        self.settings = settings

    async def handle_setup_command(self, message: Message) -> None:
        """
        Handle the /setup_trip_album command.
        
        Sends an OAuth authorization link to the user via DM.
        """
        if not self.settings.is_google_photos_configured():
            await self.send_message(
                message.chat_jid,
                "❌ Trip album feature is not configured. Please contact the administrator.",
                message.message_id,
            )
            return

        if not message.group:
            await self.send_message(
                message.chat_jid,
                "❌ This command can only be used in a group.",
                message.message_id,
            )
            return

        # Check if album already exists for this group
        existing_album = await self.session.get(TripAlbum, message.group_jid)
        if existing_album and existing_album.album_id:
            await self.send_message(
                message.chat_jid,
                f"📸 A trip album is already set up for this group!\n\n"
                f"Album: {existing_album.album_title}\n\n"
                f"All photos are being uploaded automatically.",
                message.message_id,
            )
            return

        # Generate OAuth URL with state containing group and sender info
        oauth = GoogleOAuth(
            client_id=self.settings.google_client_id,  # type: ignore
            client_secret=self.settings.google_client_secret,  # type: ignore
            redirect_uri=self.settings.google_redirect_uri,  # type: ignore
        )

        state = encode_state({
            "group_jid": message.group_jid,
            "sender_jid": message.sender_jid,
        })

        auth_url = oauth.generate_auth_url(state)

        # Send the OAuth link via DM to the user
        try:
            await self.send_message(
                message.sender_jid,
                f"🔐 *Trip Album Setup*\n\n"
                f"Click the link below to authorize Google Photos access for the group "
                f"*{message.group.group_name or 'your group'}*:\n\n"
                f"{auth_url}\n\n"
                f"This will create a shared album where all photos from the group "
                f"will be automatically uploaded.",
            )
            await self.send_message(
                message.chat_jid,
                f"📬 I've sent you a private message with the setup link. "
                f"Please check your DMs!",
                message.message_id,
            )
        except Exception as e:
            logger.error(f"Failed to send OAuth link: {e}")
            await self.send_message(
                message.chat_jid,
                "❌ Failed to send the setup link. Please try again later.",
                message.message_id,
            )


class TripPhotoHandler(BaseHandler):
    """Handles uploading photos from groups to their trip albums."""

    def __init__(
        self,
        session: AsyncSession,
        whatsapp: WhatsAppClient,
        embedding_client: AsyncClient,
        settings: Settings,
    ):
        super().__init__(session, whatsapp, embedding_client)
        self.settings = settings

    async def __call__(self, message: Message) -> None:
        """
        Process an image message and upload it to the group's trip album.
        
        Args:
            message: The message containing the image.
        """
        logger.info(f"TripPhotoHandler called: media_url={message.media_url}, group_jid={message.group_jid}")
        
        if not message.media_url or not message.group_jid:
            logger.warning(f"Missing media_url or group_jid: media_url={message.media_url}, group_jid={message.group_jid}")
            return

        # Get the trip album for this group
        trip_album = await self.session.get(TripAlbum, message.group_jid)
        logger.info(f"Trip album lookup: found={trip_album is not None}, album_id={trip_album.album_id if trip_album else None}")
        
        if not trip_album or not trip_album.album_id:
            logger.info(f"No trip album set up for group {message.group_jid}")
            return  # No album set up for this group

        if not trip_album.google_refresh_token:
            logger.warning(f"No refresh token for group {message.group_jid}")
            return

        # Ensure we have a valid access token
        access_token = await self._get_valid_access_token(trip_album)
        if not access_token:
            logger.error(f"Failed to get valid access token for group {message.group_jid}")
            return

        # Download the media from WhatsApp
        try:
            media_bytes = await self._download_media(message.media_url)
        except Exception as e:
            logger.error(f"Failed to download media: {e}")
            return

        # Determine the filename and mime type
        filename = f"photo_{message.message_id}.jpg"
        mime_type = "image/jpeg"

        # Check the media URL for file extension hints
        if message.media_url:
            if ".png" in message.media_url.lower():
                filename = f"photo_{message.message_id}.png"
                mime_type = "image/png"
            elif ".gif" in message.media_url.lower():
                filename = f"photo_{message.message_id}.gif"
                mime_type = "image/gif"
            elif ".webp" in message.media_url.lower():
                filename = f"photo_{message.message_id}.webp"
                mime_type = "image/webp"

        # Upload to Google Photos
        try:
            async with GooglePhotosClient(access_token) as photos_client:
                description = None
                if message.text:
                    # Use the caption as description
                    description = message.text.replace("[[Attached Image]] ", "")

                await photos_client.upload_to_album(
                    media_bytes=media_bytes,
                    filename=filename,
                    album_id=trip_album.album_id,
                    description=description,
                    mime_type=mime_type,
                )
                logger.info(
                    f"Uploaded photo {message.message_id} to album {trip_album.album_id}"
                )
        except Exception as e:
            logger.error(f"Failed to upload photo to Google Photos: {e}")

    async def _get_valid_access_token(self, trip_album: TripAlbum) -> Optional[str]:
        """
        Get a valid access token, refreshing if necessary.
        
        Args:
            trip_album: The TripAlbum record.
            
        Returns:
            A valid access token, or None if refresh failed.
        """
        if not trip_album.is_token_expired() and trip_album.google_access_token:
            return trip_album.google_access_token

        # Token is expired, refresh it
        if not trip_album.google_refresh_token:
            return None

        oauth = GoogleOAuth(
            client_id=self.settings.google_client_id,  # type: ignore
            client_secret=self.settings.google_client_secret,  # type: ignore
            redirect_uri=self.settings.google_redirect_uri,  # type: ignore
        )

        try:
            token_response = await oauth.refresh_access_token(
                trip_album.google_refresh_token
            )
            
            # Update the trip album with new tokens
            trip_album.google_access_token = token_response.access_token
            trip_album.token_expiry = oauth.calculate_expiry(token_response.expires_in)
            if token_response.refresh_token:
                trip_album.google_refresh_token = token_response.refresh_token
            
            await upsert(self.session, trip_album)
            await self.session.commit()
            
            return token_response.access_token
        except Exception as e:
            logger.error(f"Failed to refresh access token: {e}")
            return None

    async def _download_media(self, media_url: str) -> bytes:
        """
        Download media from the WhatsApp server.
        
        Args:
            media_url: The media path/URL from WhatsApp.
            
        Returns:
            The media bytes.
            
        Raises:
            httpx.HTTPStatusError: If the download fails.
        """
        # The media_url from WhatsApp is typically a path on the WhatsApp server
        # We need to construct the full URL using the WhatsApp host
        # Ensure there's a / between host and path
        host = self.settings.whatsapp_host.rstrip("/")
        path = media_url.lstrip("/")
        full_url = f"{host}/{path}"
        logger.info(f"Downloading media from: {full_url}")
        
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            # Add basic auth if configured
            headers = {}
            if (
                self.settings.whatsapp_basic_auth_user
                and self.settings.whatsapp_basic_auth_password
            ):
                import base64
                auth_str = base64.b64encode(
                    f"{self.settings.whatsapp_basic_auth_user}:{self.settings.whatsapp_basic_auth_password}".encode()
                ).decode()
                headers["Authorization"] = f"Basic {auth_str}"

            response = await client.get(full_url, headers=headers)
            response.raise_for_status()
            return response.content

