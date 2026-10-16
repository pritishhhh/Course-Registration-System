import os
import base64
import json
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


def auth_config():
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    if not url.startswith("https://") or not key:
        raise HTTPException(503, "Authentication is not configured.")
    # Fail closed if an administrator accidentally supplies a privileged key.
    if not key.startswith("sb_publishable_"):
        try:
            payload = key.split(".")[1]
            role = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["role"]
            if role != "anon":
                raise ValueError("Not a public key")
        except (IndexError, ValueError, KeyError, TypeError):
            raise HTTPException(503, "A Supabase publishable or anon key is required.") from None
    return url, key


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Sign in to continue.", headers={"WWW-Authenticate": "Bearer"})
    url, key = auth_config()
    try:
        # /user verifies the token with the issuer; decoding a JWT is insufficient.
        response = httpx.get(f"{url}/auth/v1/user", headers={
            "apikey": key, "Authorization": f"Bearer {credentials.credentials}",
        }, timeout=5)
        if response.status_code in (401, 403):
            raise HTTPException(401, "Your session has expired. Sign in again.")
        response.raise_for_status()
        user = response.json()
        subject = str(UUID(user["id"]))
        email = user.get("email", "")
        if not user.get("email_confirmed_at") or not 3 <= len(email) <= 320:
            raise HTTPException(403, "Confirm your email before registering.")
        return {"subject": subject, "email": email}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(503, "Authentication is temporarily unavailable.") from None
