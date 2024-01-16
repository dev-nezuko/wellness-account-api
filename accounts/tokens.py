"""Local verification of Cognito access tokens against the user pool's JWKS."""
from functools import lru_cache

import jwt
from django.conf import settings

ALGORITHMS = ['RS256']
REQUIRED_CLAIMS = ['exp', 'iat', 'iss', 'sub', 'token_use', 'client_id', 'username']
CLOCK_SKEW_SECONDS = 5


class InvalidAccessToken(Exception):
    """The bearer token is not a current access token issued for this app client."""


class KeySetUnavailable(Exception):
    """The user pool's signing keys could not be fetched."""


def cognito_issuer():
    return f'https://cognito-idp.{settings.COGNITO_REGION}.amazonaws.com/{settings.COGNITO_USER_POOL_ID}'


@lru_cache(maxsize=4)
def jwks_client(jwks_url):
    # One client per pool so fetched keys are cached across requests.
    return jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600, timeout=5)


def verify_access_token(token):
    """Return the token's claims, or raise InvalidAccessToken / KeySetUnavailable."""
    issuer = cognito_issuer()
    try:
        signing_key = jwks_client(f'{issuer}/.well-known/jwks.json').get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=ALGORITHMS,
            issuer=issuer,
            leeway=CLOCK_SKEW_SECONDS,
            # Cognito access tokens carry client_id instead of aud; it is checked below.
            options={'require': REQUIRED_CLAIMS, 'verify_aud': False},
        )
    except jwt.PyJWKClientConnectionError:
        raise KeySetUnavailable() from None
    except jwt.PyJWTError:
        raise InvalidAccessToken() from None
    if claims['token_use'] != 'access' or claims['client_id'] != settings.COGNITO_CLIENT_ID:
        raise InvalidAccessToken()
    return claims
