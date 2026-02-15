"""Azure Active Directory OIDC authentication via MSAL."""

from __future__ import annotations

import msal

from app.config.settings import settings

# Authority URL for Azure AD
_AUTHORITY = f"https://login.microsoftonline.com/{settings.azure_ad_tenant_id}"

# Scopes requested during auth
_SCOPES = ["User.Read"]


def _build_msal_app() -> msal.ConfidentialClientApplication:
    """Create an MSAL confidential client application."""
    return msal.ConfidentialClientApplication(
        client_id=settings.azure_ad_client_id,
        client_credential=settings.azure_ad_client_secret,
        authority=_AUTHORITY,
    )


def get_auth_url(state: str | None = None) -> str:
    """Return the Azure AD authorization URL for the OIDC redirect flow."""
    app = _build_msal_app()
    flow = app.initiate_auth_code_flow(
        scopes=_SCOPES,
        redirect_uri=settings.azure_ad_redirect_uri,
        state=state,
    )
    return flow.get("auth_uri", ""), flow


def exchange_code_for_token(auth_code_flow: dict, auth_response: dict) -> dict | None:
    """
    Exchange the authorization code for tokens.

    Returns the MSAL result dict containing 'access_token', 'id_token_claims', etc.
    Returns None on failure.
    """
    app = _build_msal_app()
    result = app.acquire_token_by_auth_code_flow(
        auth_code_flow=auth_code_flow,
        auth_response=auth_response,
    )
    if "error" in result:
        return None
    return result


def get_user_info(result: dict) -> dict:
    """
    Extract user information from the MSAL token result.

    Returns a dict with: email, display_name, azure_oid.
    """
    claims = result.get("id_token_claims", {})
    return {
        "email": claims.get("preferred_username", claims.get("email", "")),
        "display_name": claims.get("name", ""),
        "azure_oid": claims.get("oid", ""),
    }
