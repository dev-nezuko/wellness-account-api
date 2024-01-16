import graphene
import boto3
from botocore.exceptions import ClientError

# AWS Cognito settings (replace with your values)
COGNITO_USER_POOL_ID = 'eu-north-1_6Yucu5ItA'
COGNITO_CLIENT_ID = '5g7inc6rbu678beipjgq74fjod'
COGNITO_REGION = 'eu-north-1'

# Initialize Cognito client
cognito_client = boto3.client('cognito-idp', region_name=COGNITO_REGION)

# User type
class UserType(graphene.ObjectType):
    id = graphene.String()
    name = graphene.String()
    username = graphene.String()
    email = graphene.String()
    # Add other user attributes as needed

# Queries
class Query(graphene.ObjectType):
    get_user = graphene.Field(UserType, username=graphene.String(required=True))

    def resolve_get_user(self, info, username):
        try:
            response = cognito_client.admin_get_user(
                UserPoolId=COGNITO_USER_POOL_ID,
                Username=username
            )
            user_attributes = {attr['Name']: attr['Value'] for attr in response['UserAttributes']}
            return UserType(id=user_attributes.get('sub'), name=user_attributes.get('name'),username=username, email=user_attributes.get('email'))
        except ClientError as error:
            raise Exception(str(error))

# Mutations
class SignupMutation(graphene.Mutation):
    class Arguments:
        username = graphene.String(required=True)
        password = graphene.String(required=True)
        email = graphene.String(required=True)

    user = graphene.Field(UserType)

    def mutate(self, info, username, password, email):
        try:
            cognito_client.sign_up(
                ClientId=COGNITO_CLIENT_ID,
                Username=username,
                Password=password,
                UserAttributes=[
                    {'Name': 'email', 'Value': email}
                ]
            )
            return SignupMutation(user=UserType(username=username, email=email))
        except ClientError as error:
            raise Exception(str(error))

class SigninMutation(graphene.Mutation):
    class Arguments:
        username = graphene.String(required=True)
        password = graphene.String(required=True)

    success = graphene.Boolean()

    def mutate(self, info, username, password):
        try:
            cognito_client.initiate_auth(
                ClientId=COGNITO_CLIENT_ID,
                AuthFlow='USER_PASSWORD_AUTH',
                AuthParameters={'USERNAME': username, 'PASSWORD': password}
            )
            return SigninMutation(success=True)
        except ClientError as error:
            raise Exception(str(error))

class UpdateUserMutation(graphene.Mutation):
    class Arguments:
        username = graphene.String(required=True)
        email = graphene.String()

    success = graphene.Boolean()

    def mutate(self, info, username, email=None):
        attributes = []
        if email:
            attributes.append({'Name': 'email', 'Value': email})

        if attributes:
            try:
                cognito_client.admin_update_user_attributes(
                    UserPoolId=COGNITO_USER_POOL_ID,
                    Username=username,
                    UserAttributes=attributes
                )
                return UpdateUserMutation(success=True)
            except ClientError as error:
                raise Exception(str(error))
        else:
            return UpdateUserMutation(success=False)

class Mutation(graphene.ObjectType):
    signup = SignupMutation.Field()
    signin = SigninMutation.Field()
    update_user = UpdateUserMutation.Field()

schema = graphene.Schema(query=Query, mutation=Mutation)



# import graphene
# import requests

# class MealType(graphene.ObjectType):
#     userId = graphene.ID()
#     date = graphene.String()
#     name = graphene.String()
#     calories = graphene.Int()
#     MealId = graphene.ID()

# class Query(graphene.ObjectType):
#     list_meals = graphene.List(MealType, user_id=graphene.ID(required=True))

#     def resolve_list_meals(self, info, user_id):
#         auth_header = info.context.META.get('HTTP_AUTHORIZATION')
#         if not auth_header:
#             raise Exception("Authorization header is required")

#         # AWS AppSync GraphQL endpoint and query
#         graphql_endpoint = 'https://jvztlvvvhraivddtrhy3ul27iq.appsync-api.eu-north-1.amazonaws.com/graphql'
#         graphql_query = f'''
#         query ListMeals {{
#             listMeals(userId: "{user_id}") {{
#                 userId
#                 date
#                 name
#                 calories
#                 MealId
#             }}
#         }}
#         '''

#         # Headers including the authorization token
#         headers = {
#             'Content-Type': 'application/json',
#             'Authorization': auth_header  # Replace with the appropriate token
#         }

#         # Request to AWS AppSync
#         response = requests.post(graphql_endpoint, json={'query': graphql_query}, headers=headers)
#         meals_data = response.json().get('data', {}).get('listMeals', [])
#         return [MealType(**meal) for meal in meals_data]

# # Define the schema
# schema = graphene.Schema(query=Query)
