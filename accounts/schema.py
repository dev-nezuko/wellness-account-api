import logging
from contextlib import contextmanager
from functools import lru_cache

import boto3
import graphene
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from graphql import GraphQLError

from accounts.tokens import InvalidAccessToken, KeySetUnavailable, verify_access_token

logger = logging.getLogger(__name__)

BAD_TOKEN = 'The access token is invalid or expired'
BAD_CREDENTIALS = 'Incorrect username or password'
BAD_CODE = 'The confirmation code is invalid or expired'
UNAVAILABLE = 'Account service is unavailable'

# Client-safe messages for Cognito error codes that callers can act on.
# Anything else becomes a generic message; Cognito's own text is never returned.
SHARED_ERROR_MESSAGES = {
    'TooManyRequestsException': 'Too many requests, try again later',
    'LimitExceededException': 'Too many requests, try again later',
    'TooManyFailedAttemptsException': 'Too many failed attempts, try again later',
    'InvalidPasswordException': 'The password does not meet the account password policy',
}


def require_cognito_settings():
    if not (settings.COGNITO_REGION and settings.COGNITO_USER_POOL_ID and settings.COGNITO_CLIENT_ID):
        raise GraphQLError('Configure Cognito before using account operations')


@lru_cache(maxsize=1)
def get_cognito_client():
    require_cognito_settings()
    return boto3.client('cognito-idp', region_name=settings.COGNITO_REGION)


@contextmanager
def cognito_errors(messages):
    """Turn Cognito/botocore failures into client-safe GraphQL errors."""
    try:
        yield
    except ClientError as exc:
        code = exc.response.get('Error', {}).get('Code', 'Unknown')
        message = messages.get(code) or SHARED_ERROR_MESSAGES.get(code)
        if message is None:
            logger.warning('Cognito %s failed with %s', exc.operation_name, code)
            message = 'The account request could not be completed'
        raise GraphQLError(message) from None
    except BotoCoreError as exc:
        logger.error('Cognito is unreachable: %s', type(exc).__name__)
        raise GraphQLError(UNAVAILABLE) from None


class UserType(graphene.ObjectType):
    id = graphene.String()
    name = graphene.String()
    username = graphene.String()
    email = graphene.String()


def profile_from(response):
    attributes = {item['Name']: item['Value'] for item in response.get('UserAttributes', [])}
    return UserType(id=attributes.get('sub'), name=attributes.get('name'), username=response['Username'], email=attributes.get('email'))


class Query(graphene.ObjectType):
    get_user = graphene.Field(UserType, username=graphene.String(required=True))

    def resolve_get_user(self, info, username):
        authorization = getattr(info.context, 'headers', {}).get('Authorization', '')
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            raise GraphQLError('A Cognito access token is required')
        require_cognito_settings()
        try:
            claims = verify_access_token(parts[1])
        except InvalidAccessToken:
            raise GraphQLError(BAD_TOKEN) from None
        except KeySetUnavailable:
            raise GraphQLError(UNAVAILABLE) from None
        if claims['username'] != username:
            raise GraphQLError('Only your own canonical username can be requested')
        # Still ask Cognito: it rejects tokens revoked by sign-out before they expire.
        with cognito_errors({'NotAuthorizedException': BAD_TOKEN, 'UserNotFoundException': BAD_TOKEN}):
            response = get_cognito_client().get_user(AccessToken=parts[1])
        if response.get('Username') != username:
            raise GraphQLError('Only your own canonical username can be requested')
        return profile_from(response)


class SignupMutation(graphene.Mutation):
    class Arguments:
        username = graphene.String(required=True)
        name = graphene.String(required=True)
        password = graphene.String(required=True)
        email = graphene.String(required=True)

    user = graphene.Field(UserType)

    def mutate(self, info, username, name, password, email):
        with cognito_errors({'UsernameExistsException': 'That username is not available'}):
            get_cognito_client().sign_up(
                ClientId=settings.COGNITO_CLIENT_ID,
                Username=username,
                Password=password,
                UserAttributes=[
                    {'Name': 'email', 'Value': email},
                    {'Name': 'name', 'Value': name},
                ],
            )
        return SignupMutation(user=UserType(username=username, email=email))


class UserConfirmationMutation(graphene.Mutation):
    class Arguments:
        username = graphene.String(required=True)
        otp = graphene.String(required=True)

    success = graphene.Boolean()

    def mutate(self, info, username, otp):
        # Unknown users get the same answer as wrong codes so usernames can't be probed.
        with cognito_errors({'CodeMismatchException': BAD_CODE, 'ExpiredCodeException': BAD_CODE, 'UserNotFoundException': BAD_CODE}):
            get_cognito_client().confirm_sign_up(
                ClientId=settings.COGNITO_CLIENT_ID,
                Username=username,
                ConfirmationCode=otp,
            )
        return UserConfirmationMutation(success=True)


class SigninMutation(graphene.Mutation):
    class Arguments:
        username = graphene.String(required=True)
        password = graphene.String(required=True)

    accessToken = graphene.String()
    refreshToken = graphene.String()
    userId = graphene.String()
    userName = graphene.String()
    userEmail = graphene.String()

    def mutate(self, info, username, password):
        with cognito_errors({
            'NotAuthorizedException': BAD_CREDENTIALS,
            'UserNotFoundException': BAD_CREDENTIALS,
            'UserNotConfirmedException': 'Confirm the account before signing in',
            'PasswordResetRequiredException': 'A password reset is required before signing in',
        }):
            res = get_cognito_client().initiate_auth(
                ClientId=settings.COGNITO_CLIENT_ID,
                AuthFlow='USER_PASSWORD_AUTH',
                AuthParameters={'USERNAME': username, 'PASSWORD': password},
            )
        if 'AuthenticationResult' not in res:
            raise GraphQLError('Additional authentication challenge is not implemented')
        tokens = res['AuthenticationResult']
        with cognito_errors({}):
            profile = profile_from(get_cognito_client().get_user(AccessToken=tokens['AccessToken']))
        return SigninMutation(
            accessToken=tokens['AccessToken'],
            refreshToken=tokens.get('RefreshToken'),
            userId=profile.id,
            userName=profile.username,
            userEmail=profile.email,
        )


class Mutation(graphene.ObjectType):
    signup = SignupMutation.Field()
    signin = SigninMutation.Field()
    confirm_user = UserConfirmationMutation.Field()


schema = graphene.Schema(query=Query, mutation=Mutation)
