"""Google OAuth callback endpoint for trip album setup."""

import base64
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from api.deps import get_db_async_session, get_whatsapp
from config import Settings, get_settings
from google_photos import GoogleOAuth, GooglePhotosClient
from models import TripAlbum, Group
from models.upsert import upsert
from whatsapp import WhatsAppClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oauth/google", tags=["oauth"])


def decode_state(state: str) -> dict:
    """Decode the base64 state parameter back to a dict."""
    try:
        decoded = base64.urlsafe_b64decode(state.encode()).decode()
        return json.loads(decoded)
    except Exception as e:
        logger.error(f"Failed to decode state: {e}")
        raise HTTPException(status_code=400, detail="Invalid state parameter")


def encode_state(data: dict) -> str:
    """Encode a dict to a base64 state parameter."""
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()


@router.get("/callback", response_class=HTMLResponse)
async def google_oauth_callback(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_async_session)],
    whatsapp: Annotated[WhatsAppClient, Depends(get_whatsapp)],
    settings: Annotated[Settings, Depends(get_settings)],
    code: Annotated[str | None, Query(description="Authorization code from Google")] = None,
    state: Annotated[str | None, Query(description="State parameter with group info")] = None,
    error: Annotated[str | None, Query(description="Error from Google")] = None,
    error_description: Annotated[str | None, Query(description="Error description")] = None,
) -> HTMLResponse:
    """
    OAuth2 callback endpoint. Google redirects here after user authorization.
    
    The state parameter contains the group_jid and sender_jid encoded in base64.
    """
    # Handle OAuth errors (user denied, etc.)
    if error:
        logger.warning(f"OAuth error: {error} - {error_description}")
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Authorization Failed</title>
                <style>
                    body {{
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        min-height: 100vh;
                        margin: 0;
                        background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
                    }}
                    .card {{
                        background: white;
                        padding: 40px;
                        border-radius: 16px;
                        box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                        text-align: center;
                        max-width: 400px;
                    }}
                    .error-icon {{
                        font-size: 64px;
                        margin-bottom: 20px;
                    }}
                    h1 {{ color: #333; }}
                    p {{ color: #666; line-height: 1.6; }}
                </style>
            </head>
            <body>
                <div class="card">
                    <div class="error-icon">❌</div>
                    <h1>Authorization Failed</h1>
                    <p>{error_description or error}</p>
                    <p style="margin-top: 20px; font-size: 14px; color: #999;">
                        Please try again by sending /setup_trip_album in the WhatsApp group.
                    </p>
                </div>
            </body>
            </html>
            """,
            status_code=200,
        )

    # Validate required parameters
    if not code or not state:
        logger.error(f"Missing required parameters: code={bool(code)}, state={bool(state)}")
        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Invalid Request</title>
                <style>
                    body {
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        min-height: 100vh;
                        margin: 0;
                        background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
                    }
                    .card {
                        background: white;
                        padding: 40px;
                        border-radius: 16px;
                        box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                        text-align: center;
                        max-width: 400px;
                    }
                    .error-icon { font-size: 64px; margin-bottom: 20px; }
                    h1 { color: #333; }
                    p { color: #666; line-height: 1.6; }
                </style>
            </head>
            <body>
                <div class="card">
                    <div class="error-icon">⚠️</div>
                    <h1>Invalid Request</h1>
                    <p>Missing required parameters. Please start the authorization process again.</p>
                    <p style="margin-top: 20px; font-size: 14px; color: #999;">
                        Send /setup_trip_album in your WhatsApp group to try again.
                    </p>
                </div>
            </body>
            </html>
            """,
            status_code=200,
        )

    if not settings.is_google_photos_configured():
        raise HTTPException(
            status_code=500,
            detail="Google Photos OAuth is not configured",
        )

    # Decode state to get group and user info
    state_data = decode_state(state)
    group_jid = state_data.get("group_jid")
    sender_jid = state_data.get("sender_jid")

    if not group_jid:
        raise HTTPException(status_code=400, detail="Missing group_jid in state")

    # Verify the group exists
    group = await session.get(Group, group_jid)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # Exchange code for tokens
    oauth = GoogleOAuth(
        client_id=settings.google_client_id,  # type: ignore
        client_secret=settings.google_client_secret,  # type: ignore
        redirect_uri=settings.google_redirect_uri,  # type: ignore
    )

    try:
        token_response = await oauth.exchange_code(code)
    except Exception as e:
        logger.error(f"Failed to exchange OAuth code: {e}")
        raise HTTPException(status_code=400, detail="Failed to exchange authorization code")

    # Create the album in Google Photos
    album_title = f"Trip: {group.group_name or group_jid}"
    
    async with GooglePhotosClient(token_response.access_token) as photos_client:
        # Create the album
        try:
            album = await photos_client.create_album(album_title)
            logger.info(f"Album created successfully: id={album.id}, title={album.title}")
        except Exception as e:
            error_detail = str(e)
            if hasattr(e, 'response'):
                try:
                    error_detail = f"{e} - Response: {e.response.text}"  # type: ignore
                except Exception:
                    pass
            logger.error(f"Failed to create album: {error_detail}")
            raise HTTPException(status_code=500, detail="Failed to create album in Google Photos")

        # Note: Google deprecated the albums.share API method in 2024
        # Users must manually share the album from Google Photos
        # We use the productUrl which links to the album in the owner's account
        album_url = album.product_url
        logger.info(f"Album created with productUrl: {album_url}")

    # Save the TripAlbum record
    trip_album = TripAlbum(
        group_jid=group_jid,
        album_id=album.id,
        album_title=album.title or album_title,
        album_url=album_url,
        google_refresh_token=token_response.refresh_token,
        google_access_token=token_response.access_token,
        token_expiry=oauth.calculate_expiry(token_response.expires_in),
        created_by_jid=sender_jid,
    )

    await upsert(session, trip_album)
    await session.commit()

    # Send confirmation message to the group
    # Note: User must manually share the album from Google Photos for others to view
    try:
        await whatsapp.send_message(
            request={
                "phone": group_jid,
                "message": f"✅ Trip album created successfully!\n\n"
                f"📸 Album: {album.title}\n"
                f"🔗 {album_url}\n\n"
                f"⚠️ *Important*: To let others view the album, please open the link above "
                f"and tap 'Share' → 'Get link' in Google Photos.\n\n"
                f"All photos sent in this group will be uploaded automatically.",
            }
        )
    except Exception as e:
        logger.warning(f"Failed to send confirmation message: {e}")

    # Return a success page
    return HTMLResponse(
        content=f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Trip Album Setup Complete</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    min-height: 100vh;
                    margin: 0;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                }}
                .card {{
                    background: white;
                    padding: 40px;
                    border-radius: 16px;
                    box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                    text-align: center;
                    max-width: 400px;
                }}
                .success-icon {{
                    font-size: 64px;
                    margin-bottom: 20px;
                }}
                h1 {{
                    color: #333;
                    margin-bottom: 10px;
                }}
                p {{
                    color: #666;
                    line-height: 1.6;
                }}
                .album-name {{
                    background: #f0f0f0;
                    padding: 10px 20px;
                    border-radius: 8px;
                    margin: 20px 0;
                    font-weight: 500;
                }}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="success-icon">✅</div>
                <h1>Album Created!</h1>
                <div class="album-name">{album.title}</div>
                <p>
                    Your trip album has been set up successfully.
                    All photos sent in the WhatsApp group will now be
                    automatically uploaded to your Google Photos album.
                </p>
                <p style="margin-top: 20px; font-size: 14px; color: #999;">
                    You can close this window now.
                </p>
            </div>
        </body>
        </html>
        """,
        status_code=200,
    )


@router.get("/error", response_class=HTMLResponse)
async def google_oauth_error(
    error: Annotated[str, Query(description="Error from Google")],
    error_description: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    """Handle OAuth errors from Google."""
    return HTMLResponse(
        content=f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Authorization Failed</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    min-height: 100vh;
                    margin: 0;
                    background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
                }}
                .card {{
                    background: white;
                    padding: 40px;
                    border-radius: 16px;
                    box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                    text-align: center;
                    max-width: 400px;
                }}
                .error-icon {{
                    font-size: 64px;
                    margin-bottom: 20px;
                }}
                h1 {{
                    color: #333;
                }}
                p {{
                    color: #666;
                }}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="error-icon">❌</div>
                <h1>Authorization Failed</h1>
                <p>{error_description or error}</p>
                <p style="margin-top: 20px; font-size: 14px; color: #999;">
                    Please try again by sending /setup_trip_album in the WhatsApp group.
                </p>
            </div>
        </body>
        </html>
        """,
        status_code=200,
    )

