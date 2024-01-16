"""Argument checks that run before any Cognito call."""
import re

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from graphql import GraphQLError

# Cognito usernames: 1-128 characters, no whitespace.
USERNAME = re.compile(r'\S{1,128}')
CONFIRMATION_CODE = re.compile(r'[0-9]{6}')
CONTROL_CHARACTERS = re.compile(r'[\x00-\x1f\x7f]')
MAX_PASSWORD = 256  # Cognito's hard limit; the pool's own policy is enforced by Cognito.
MAX_NAME = 256
email_validator = EmailValidator()


def invalid(field, reason):
    return GraphQLError(f'Invalid {field}: {reason}', extensions={'field': field})


def clean_username(value):
    if not USERNAME.fullmatch(value):
        raise invalid('username', 'use 1-128 characters without spaces')
    return value


def clean_password(value):
    if not value or len(value) > MAX_PASSWORD:
        raise invalid('password', f'use 1-{MAX_PASSWORD} characters')
    return value


def clean_name(value):
    value = value.strip()
    if not value or len(value) > MAX_NAME or CONTROL_CHARACTERS.search(value):
        raise invalid('name', f'use 1-{MAX_NAME} printable characters')
    return value


def clean_email(value):
    value = value.strip()
    try:
        email_validator(value)
    except ValidationError:
        raise invalid('email', 'enter a valid email address') from None
    return value


def clean_confirmation_code(value):
    if not CONFIRMATION_CODE.fullmatch(value):
        raise invalid('otp', 'enter the 6-digit code from the confirmation email')
    return value
