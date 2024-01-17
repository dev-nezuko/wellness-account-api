import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock
from django.conf import settings

if not settings.configured:
    settings.configure(COGNITO_REGION='offline-region', COGNITO_CLIENT_ID='offline-client', COGNITO_USER_POOL_ID='offline-pool')

from botocore.exceptions import ClientError
from accounts.schema import schema


ATTRS = [{'Name': 'sub', 'Value': 'synthetic-user-id'}, {'Name': 'name', 'Value': 'Synthetic User'}, {'Name': 'email', 'Value': 'synthetic@example.invalid'}]


class AccountSchemaTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.get_user.return_value = {'Username': 'synthetic-user', 'UserAttributes': ATTRS}
        self.patch = patch('accounts.schema.get_cognito_client', return_value=self.client)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def execute(self, query, authorization=None):
        headers = {} if authorization is None else {'Authorization': authorization}
        return schema.execute(query, context_value=SimpleNamespace(headers=headers))

    def test_lookup_requires_token_before_provider_call(self):
        result = self.execute('{ getUser(username:"synthetic-user") { email } }')
        self.assertTrue(result.errors)
        self.client.get_user.assert_not_called()

    def test_lookup_returns_only_token_owner(self):
        result = self.execute('{ getUser(username:"synthetic-user") { id username email } }', 'Bearer offline-access')
        self.assertIsNone(result.errors)
        self.assertEqual(result.data['getUser']['id'], 'synthetic-user-id')
        self.client.get_user.assert_called_once_with(AccessToken='offline-access')
        self.client.admin_get_user.assert_not_called()

    def test_lookup_rejects_other_user(self):
        result = self.execute('{ getUser(username:"another-user") { email } }','Bearer offline-access')
        self.assertTrue(result.errors)
        self.assertIsNone(result.data['getUser'])

    def test_signin_reads_profile_using_returned_access_token(self):
        self.client.initiate_auth.return_value = {'AuthenticationResult': {'AccessToken': 'offline-access', 'RefreshToken': 'offline-refresh'}}
        result = self.execute('mutation { signin(username:"synthetic-user",password:"offline-password") { accessToken userEmail } }')
        self.assertIsNone(result.errors)
        self.assertEqual(result.data['signin']['userEmail'], 'synthetic@example.invalid')
        self.client.get_user.assert_called_once_with(AccessToken='offline-access')
        self.client.admin_get_user.assert_not_called()

    def test_auth_challenge_is_explicitly_unsupported(self):
        self.client.initiate_auth.return_value = {'ChallengeName': 'SMS_MFA'}
        result = self.execute('mutation { signin(username:"synthetic-user",password:"offline-password") { accessToken } }')
        self.assertIn('challenge is not implemented', str(result.errors[0]))
        self.client.get_user.assert_not_called()

    def test_provider_error_does_not_expose_details(self):
        self.client.get_user.side_effect = ClientError({'Error': {'Code': 'NotAuthorizedException', 'Message': 'PRIVATE_PROVIDER_DIAGNOSTIC'}}, 'GetUser')
        result = self.execute('{ getUser(username:"synthetic-user") { email } }','Bearer offline-access')
        self.assertTrue(result.errors)
        self.assertNotIn('PRIVATE_PROVIDER_DIAGNOSTIC', str(result.errors))

    def test_signup_and_confirmation_use_client_methods(self):
        result = self.execute('mutation { signup(username:"synthetic-user",name:"Synthetic User",password:"offline-password",email:"synthetic@example.invalid") { user { username } } }')
        self.assertIsNone(result.errors)
        self.client.sign_up.assert_called_once()
        result = self.execute('mutation { confirmUser(username:"synthetic-user",otp:"000000") { success } }')
        self.assertIsNone(result.errors)
        self.assertTrue(result.data['confirmUser']['success'])
        self.client.confirm_sign_up.assert_called_once()
