from types import SimpleNamespace
from unittest.mock import patch

import boto3
from botocore.stub import Stubber
from django.test import SimpleTestCase

from accounts.schema import schema

ATTRS = [
    {'Name': 'sub', 'Value': 'synthetic-user-id'},
    {'Name': 'name', 'Value': 'Synthetic User'},
    {'Name': 'email', 'Value': 'synthetic@example.invalid'},
]
PROFILE = {'Username': 'synthetic-user', 'UserAttributes': ATTRS}


class StubbedCognitoTestCase(SimpleTestCase):
    """Runs every Cognito call against botocore's Stubber; nothing reaches AWS."""

    def setUp(self):
        client = boto3.client(
            'cognito-idp',
            region_name='us-east-1',
            aws_access_key_id='offline',
            aws_secret_access_key='offline',
        )
        self.cognito = Stubber(client)
        self.cognito.activate()
        self.addCleanup(self.cognito.deactivate)
        patcher = patch('accounts.schema.get_cognito_client', return_value=client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def execute(self, query, authorization=None):
        headers = {} if authorization is None else {'Authorization': authorization}
        return schema.execute(query, context_value=SimpleNamespace(headers=headers))


class AccountSchemaTests(StubbedCognitoTestCase):
    def test_lookup_requires_token_before_provider_call(self):
        result = self.execute('{ getUser(username:"synthetic-user") { email } }')
        self.assertIn('access token is required', str(result.errors[0]))
        self.cognito.assert_no_pending_responses()

    def test_lookup_returns_only_token_owner(self):
        self.cognito.add_response('get_user', PROFILE, {'AccessToken': 'offline-access'})
        result = self.execute('{ getUser(username:"synthetic-user") { id username email } }', 'Bearer offline-access')
        self.assertIsNone(result.errors)
        self.assertEqual(result.data['getUser']['id'], 'synthetic-user-id')
        self.cognito.assert_no_pending_responses()

    def test_lookup_rejects_other_user(self):
        self.cognito.add_response('get_user', PROFILE, {'AccessToken': 'offline-access'})
        result = self.execute('{ getUser(username:"another-user") { email } }', 'Bearer offline-access')
        self.assertTrue(result.errors)
        self.assertIsNone(result.data['getUser'])

    def test_signin_reads_profile_using_returned_access_token(self):
        self.cognito.add_response(
            'initiate_auth',
            {'AuthenticationResult': {'AccessToken': 'offline-access', 'RefreshToken': 'offline-refresh'}},
        )
        self.cognito.add_response('get_user', PROFILE, {'AccessToken': 'offline-access'})
        result = self.execute('mutation { signin(username:"synthetic-user",password:"offline-password") { accessToken userEmail } }')
        self.assertIsNone(result.errors)
        self.assertEqual(result.data['signin']['userEmail'], 'synthetic@example.invalid')
        self.cognito.assert_no_pending_responses()

    def test_auth_challenge_is_explicitly_unsupported(self):
        self.cognito.add_response('initiate_auth', {'ChallengeName': 'SMS_MFA', 'Session': 'offline-challenge-session'})
        result = self.execute('mutation { signin(username:"synthetic-user",password:"offline-password") { accessToken } }')
        self.assertIn('challenge is not implemented', str(result.errors[0]))

    def test_provider_error_does_not_expose_details(self):
        self.cognito.add_client_error('get_user', 'NotAuthorizedException', 'PRIVATE_PROVIDER_DIAGNOSTIC')
        result = self.execute('{ getUser(username:"synthetic-user") { email } }', 'Bearer offline-access')
        self.assertTrue(result.errors)
        self.assertNotIn('PRIVATE_PROVIDER_DIAGNOSTIC', str(result.errors))

    def test_signup_and_confirmation_use_client_methods(self):
        self.cognito.add_response('sign_up', {'UserConfirmed': False, 'UserSub': 'synthetic-user-id'})
        result = self.execute(
            'mutation { signup(username:"synthetic-user",name:"Synthetic User",'
            'password:"offline-password",email:"synthetic@example.invalid") { user { username } } }'
        )
        self.assertIsNone(result.errors)
        self.cognito.add_response(
            'confirm_sign_up',
            {},
            {'ClientId': 'offline-client-id', 'Username': 'synthetic-user', 'ConfirmationCode': '000000'},
        )
        result = self.execute('mutation { confirmUser(username:"synthetic-user",otp:"000000") { success } }')
        self.assertIsNone(result.errors)
        self.assertTrue(result.data['confirmUser']['success'])
        self.cognito.assert_no_pending_responses()


class GraphQLEndpointTests(StubbedCognitoTestCase):
    def test_http_endpoint_serves_the_schema(self):
        self.cognito.add_response('get_user', PROFILE, {'AccessToken': 'offline-access'})
        response = self.client.post(
            '/graphql',
            {'query': '{ getUser(username:"synthetic-user") { username } }'},
            content_type='application/json',
            HTTP_AUTHORIZATION='Bearer offline-access',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'data': {'getUser': {'username': 'synthetic-user'}}})
