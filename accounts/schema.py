from functools import lru_cache

import boto3
import graphene
from botocore.exceptions import ClientError
from django.conf import settings
from graphql import GraphQLError


@lru_cache(maxsize=1)
def get_cognito_client():
    if not settings.COGNITO_REGION:
        raise GraphQLError('Configure Cognito before using account operations')
    return boto3.client('cognito-idp', region_name=settings.COGNITO_REGION)


# User type
class UserType(graphene.ObjectType):
    id = graphene.String()
    name = graphene.String()
    username = graphene.String()
    email = graphene.String()

# Queries
class Query(graphene.ObjectType):
    get_user = graphene.Field(UserType, username=graphene.String(required=True))

    def resolve_get_user(self, info, username):
        authorization = getattr(info.context, 'headers', {}).get('Authorization', '')
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            raise GraphQLError('A Cognito access token is required')
        try:
            response = get_cognito_client().get_user(AccessToken=parts[1])
        except ClientError:
            raise GraphQLError('Cognito request failed') from None
        if response.get('Username') != username:
            raise GraphQLError('Only your own canonical username can be requested')
        attributes = {item['Name']: item['Value'] for item in response.get('UserAttributes', [])}
        return UserType(id=attributes.get('sub'), name=attributes.get('name'), username=response['Username'], email=attributes.get('email'))

# Mutations
class SignupMutation(graphene.Mutation):
    class Arguments:
        username = graphene.String(required=True)
        name = graphene.String(required=True)
        password = graphene.String(required=True)
        email = graphene.String(required=True)

    user = graphene.Field(UserType)

    def mutate(self, info, username, name, password, email):
        try:
            get_cognito_client().sign_up(
                ClientId=settings.COGNITO_CLIENT_ID,
                Username=username,
                Password=password,
                UserAttributes=[
                    {'Name': 'email', 'Value': email},
                    {'Name': 'name', 'Value': name}
                ]
            )
            return SignupMutation(user=UserType(username=username, email=email))
        except ClientError:
            raise GraphQLError('Cognito request failed') from None
        
class UserConfirmationMutation(graphene.Mutation):
    class Arguments:
        username = graphene.String(required=True)
        otp = graphene.String(required=True)

    success = graphene.Boolean()

    def mutate(self, info, username, otp):
        try:
            get_cognito_client().confirm_sign_up(
                ClientId=settings.COGNITO_CLIENT_ID,
                Username=username,
                ConfirmationCode=otp
            )
            
            return UserConfirmationMutation(success=True)
        except ClientError:
            raise GraphQLError('Cognito request failed') from None

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
        try:
            res = get_cognito_client().initiate_auth(
                ClientId=settings.COGNITO_CLIENT_ID,
                AuthFlow='USER_PASSWORD_AUTH',
                AuthParameters={'USERNAME': username, 'PASSWORD': password}
            )
            if 'AuthenticationResult' not in res:
                raise GraphQLError('Additional authentication challenge is not implemented')
            token = res['AuthenticationResult']['AccessToken']
            rtoken = res['AuthenticationResult']['RefreshToken']
            response = get_cognito_client().get_user(AccessToken=token)
            user_attributes = {attr['Name']: attr['Value'] for attr in response['UserAttributes']}
            
            return SigninMutation(accessToken=token, refreshToken=rtoken, userId=user_attributes.get('sub'), userName=response['Username'], userEmail=user_attributes.get('email'))
        except ClientError:
            raise GraphQLError('Cognito request failed') from None

class Mutation(graphene.ObjectType):
    signup = SignupMutation.Field()
    signin = SigninMutation.Field()
    confirm_user = UserConfirmationMutation.Field()

schema = graphene.Schema(query=Query, mutation=Mutation)
