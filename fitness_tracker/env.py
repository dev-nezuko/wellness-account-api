import os


def env_list(name, default=''):
    """Comma-separated env value as a list, ignoring blanks and stray spaces."""
    return [item.strip() for item in os.getenv(name, default).split(',') if item.strip()]


def env_origins(name):
    # django-cors-headers rejects origins with a path, so drop a trailing slash.
    return [origin.rstrip('/') for origin in env_list(name)]
