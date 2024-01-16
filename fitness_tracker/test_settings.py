"""Settings for the test suite: offline Cognito placeholders, never real credentials."""
import os

os.environ.setdefault('SECRET_KEY', 'test-only-signing-key-not-a-secret')

from .settings import *

COGNITO_REGION = 'us-east-1'
COGNITO_USER_POOL_ID = 'us-east-1_OfflinePool'
COGNITO_CLIENT_ID = 'offline-client-id'
