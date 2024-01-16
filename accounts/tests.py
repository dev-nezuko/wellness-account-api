import time
from types import SimpleNamespace
from unittest.mock import patch

import boto3
import jwt
from botocore.exceptions import EndpointConnectionError
from botocore.stub import Stubber
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import SimpleTestCase, override_settings

from accounts.schema import schema
from accounts.tokens import cognito_issuer, jwks_client

# Generated per test run; the stubbed JWKS below is the only key set the code sees.
SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KEY_ID = 'offline-test-key'
STUB_JWKS = {'keys': [{**jwt.algorithms.RSAAlgorithm.to_jwk(SIGNING_KEY.public_key(), as_dict=True), 'kid': KEY_ID, 'alg': 'RS256', 'use': 'sig'}]}


def access_token(key=SIGNING_KEY, kid=KEY_ID, algorithm='RS256', **overrides):
    now = int(time.time())
    claims = {
        'sub': 'synthetic-user-id',
        'iss': cognito_issuer(),
        'client_id': 'offline-client-id',
        'token_use': 'access',
        'username': 'synthetic-user',
        'iat': now,
        'exp': now + 600,
    }
    claims.update(overrides)
    claims = {name: value for name, value in claims.items() if value is not None}
    return jwt.encode(claims, key, algorithm=algorithm, headers={'kid': kid})

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
        self.cognito_client = client
        self.cognito = Stubber(client)
        self.cognito.activate()
        self.addCleanup(self.cognito.deactivate)
        patcher = patch('accounts.schema.get_cognito_client', return_value=client)
        patcher.start()
        self.addCleanup(patcher.stop)
        jwks_client.cache_clear()
        jwks_patcher = patch('jwt.PyJWKClient.fetch_data', return_value=STUB_JWKS)
        self.jwks_fetch = jwks_patcher.start()
        self.addCleanup(jwks_patcher.stop)
        self.token = access_token()

    def execute(self, query, authorization=None):
        headers = {} if authorization is None else {'Authorization': authorization}
        return schema.execute(query, context_value=SimpleNamespace(headers=headers))


class AccountSchemaTests(StubbedCognitoTestCase):
    def test_lookup_requires_token_before_provider_call(self):
        result = self.execute('{ getUser(username:"synthetic-user") { email } }')
        self.assertIn('access token is required', str(result.errors[0]))
        self.cognito.assert_no_pending_responses()

    def test_lookup_returns_only_token_owner(self):
        self.cognito.add_response('get_user', PROFILE, {'AccessToken': self.token})
        result = self.execute('{ getUser(username:"synthetic-user") { id username email } }', f'Bearer {self.token}')
        self.assertIsNone(result.errors)
        self.assertEqual(result.data['getUser']['id'], 'synthetic-user-id')
        self.cognito.assert_no_pending_responses()

    def test_lookup_rejects_other_user(self):
        result = self.execute('{ getUser(username:"another-user") { email } }', f'Bearer {self.token}')
        self.assertTrue(result.errors)
        self.assertIsNone(result.data['getUser'])
        self.cognito.assert_no_pending_responses()

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
        result = self.execute('{ getUser(username:"synthetic-user") { email } }', f'Bearer {self.token}')
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


class AccessTokenVerificationTests(StubbedCognitoTestCase):
    QUERY = '{ getUser(username:"synthetic-user") { username } }'

    def assert_rejected(self, token):
        result = self.execute(self.QUERY, f'Bearer {token}')
        self.assertIn('invalid or expired', str(result.errors[0]))
        # Rejected locally: Cognito is never asked about a token that fails verification.
        self.cognito.assert_no_pending_responses()

    def test_valid_token_is_checked_against_the_pool_jwks(self):
        self.cognito.add_response('get_user', PROFILE, {'AccessToken': self.token})
        result = self.execute(self.QUERY, f'Bearer {self.token}')
        self.assertIsNone(result.errors)
        self.jwks_fetch.assert_called_once()
        pool_jwks = 'https://cognito-idp.us-east-1.amazonaws.com/us-east-1_OfflinePool/.well-known/jwks.json'
        jwks_client(pool_jwks)
        self.assertEqual(jwks_client.cache_info().hits, 1)

    def test_rejects_token_signed_by_another_key(self):
        self.assert_rejected(access_token(key=OTHER_KEY))

    def test_rejects_unknown_key_id(self):
        self.assert_rejected(access_token(kid='not-in-the-pool'))

    def test_rejects_symmetric_algorithm(self):
        self.assert_rejected(access_token(key='offline-shared-secret-of-32-bytes!', algorithm='HS256'))

    def test_rejects_unsigned_token(self):
        self.assert_rejected(access_token(key=None, algorithm='none'))

    def test_rejects_other_issuer(self):
        self.assert_rejected(access_token(iss='https://cognito-idp.us-east-1.amazonaws.com/us-east-1_OtherPool'))

    def test_rejects_other_app_client(self):
        self.assert_rejected(access_token(client_id='another-client-id'))

    def test_rejects_id_token(self):
        self.assert_rejected(access_token(token_use='id'))

    def test_rejects_expired_token(self):
        self.assert_rejected(access_token(iat=int(time.time()) - 3600, exp=int(time.time()) - 60))

    def test_rejects_token_missing_expiry(self):
        self.assert_rejected(access_token(exp=None))

    def test_rejects_malformed_token(self):
        self.assert_rejected('not-a-jwt')

    def test_rejects_token_for_another_username_before_calling_cognito(self):
        result = self.execute('{ getUser(username:"another-user") { username } }', f'Bearer {self.token}')
        self.assertIn('Only your own', str(result.errors[0]))
        self.cognito.assert_no_pending_responses()

    def test_revoked_token_is_still_rejected_by_cognito(self):
        self.cognito.add_client_error('get_user', 'NotAuthorizedException', 'Access Token has been revoked')
        result = self.execute(self.QUERY, f'Bearer {self.token}')
        self.assertTrue(result.errors)
        self.cognito.assert_no_pending_responses()

    def test_unreachable_key_set_is_reported_without_details(self):
        self.jwks_fetch.side_effect = jwt.PyJWKClientConnectionError('PRIVATE_NETWORK_DIAGNOSTIC')
        result = self.execute(self.QUERY, f'Bearer {self.token}')
        self.assertEqual(result.errors[0].message, 'Account service is unavailable')


class CognitoErrorTests(StubbedCognitoTestCase):
    SIGNIN = 'mutation { signin(username:"synthetic-user",password:"offline-password") { accessToken } }'
    SIGNUP = (
        'mutation { signup(username:"synthetic-user",name:"Synthetic User",'
        'password:"offline-password",email:"synthetic@example.invalid") { user { username } } }'
    )
    CONFIRM = 'mutation { confirmUser(username:"synthetic-user",otp:"123456") { success } }'

    def error_for(self, query, operation, code):
        self.cognito.add_client_error(operation, code, f'PRIVATE {code} DETAIL')
        result = self.execute(query)
        self.cognito.assert_no_pending_responses()
        self.assertNotIn('PRIVATE', str(result.errors))
        return result.errors[0].message

    def test_wrong_password_and_unknown_user_look_the_same(self):
        self.assertEqual(self.error_for(self.SIGNIN, 'initiate_auth', 'NotAuthorizedException'), 'Incorrect username or password')
        self.assertEqual(self.error_for(self.SIGNIN, 'initiate_auth', 'UserNotFoundException'), 'Incorrect username or password')

    def test_unconfirmed_user_is_told_to_confirm(self):
        self.assertEqual(self.error_for(self.SIGNIN, 'initiate_auth', 'UserNotConfirmedException'), 'Confirm the account before signing in')

    def test_signup_conflicts_and_weak_passwords(self):
        self.assertEqual(self.error_for(self.SIGNUP, 'sign_up', 'UsernameExistsException'), 'That username is not available')
        self.assertIn('password policy', self.error_for(self.SIGNUP, 'sign_up', 'InvalidPasswordException'))

    def test_bad_code_and_unknown_user_look_the_same_on_confirmation(self):
        for code in ('CodeMismatchException', 'ExpiredCodeException', 'UserNotFoundException'):
            self.assertEqual(self.error_for(self.CONFIRM, 'confirm_sign_up', code), 'The confirmation code is invalid or expired')

    def test_throttling_is_reported(self):
        self.assertIn('try again later', self.error_for(self.SIGNIN, 'initiate_auth', 'TooManyRequestsException'))

    def test_unexpected_codes_get_a_generic_message(self):
        with self.assertLogs('accounts.schema', 'WARNING') as logs:
            message = self.error_for(self.SIGNUP, 'sign_up', 'InternalErrorException')
        self.assertIn('InternalErrorException', logs.output[0])
        self.assertEqual(message, 'The account request could not be completed')

    def test_unreachable_cognito_hides_the_endpoint(self):
        error = EndpointConnectionError(endpoint_url='https://cognito-idp.private-endpoint.invalid')
        with patch.object(self.cognito_client, 'initiate_auth', side_effect=error), self.assertLogs('accounts.schema', 'ERROR'):
            result = self.execute(self.SIGNIN)
        self.assertEqual(result.errors[0].message, 'Account service is unavailable')

    def test_missing_configuration_is_reported_before_any_call(self):
        with self.settings(COGNITO_USER_POOL_ID=''):
            result = self.execute('{ getUser(username:"synthetic-user") { username } }', f'Bearer {self.token}')
        self.assertIn('Configure Cognito', result.errors[0].message)


class InputValidationTests(StubbedCognitoTestCase):
    def signup(self, username='synthetic-user', name='Synthetic User', password='offline-password', email='synthetic@example.invalid'):
        query = 'mutation($u:String!,$n:String!,$p:String!,$e:String!) { signup(username:$u,name:$n,password:$p,email:$e) { user { name email } } }'
        return schema.execute(query, variables={'u': username, 'n': name, 'p': password, 'e': email}, context_value=SimpleNamespace(headers={}))

    def assert_invalid(self, result, field):
        self.assertEqual(result.errors[0].extensions, {'field': field})
        self.cognito.assert_no_pending_responses()

    def test_signup_rejects_bad_fields_before_calling_cognito(self):
        self.assert_invalid(self.signup(username=''), 'username')
        self.assert_invalid(self.signup(username='has space'), 'username')
        self.assert_invalid(self.signup(username='u' * 129), 'username')
        self.assert_invalid(self.signup(name='   '), 'name')
        self.assert_invalid(self.signup(name='Line\nbreak'), 'name')
        self.assert_invalid(self.signup(password=''), 'password')
        self.assert_invalid(self.signup(password='p' * 257), 'password')
        self.assert_invalid(self.signup(email='not-an-email'), 'email')

    def test_signup_sends_trimmed_name_and_email(self):
        self.cognito.add_response(
            'sign_up',
            {'UserConfirmed': False, 'UserSub': 'synthetic-user-id'},
            {
                'ClientId': 'offline-client-id',
                'Username': 'synthetic-user',
                'Password': 'offline-password',
                'UserAttributes': [
                    {'Name': 'email', 'Value': 'synthetic@example.invalid'},
                    {'Name': 'name', 'Value': 'Synthetic User'},
                ],
            },
        )
        result = self.signup(name='  Synthetic User ', email=' synthetic@example.invalid ')
        self.assertIsNone(result.errors)
        self.assertEqual(result.data['signup']['user'], {'name': 'Synthetic User', 'email': 'synthetic@example.invalid'})
        self.cognito.assert_no_pending_responses()

    def test_confirmation_code_must_be_six_digits(self):
        for code in ('', '12345', '1234567', 'abcdef'):
            result = self.execute(f'mutation {{ confirmUser(username:"synthetic-user",otp:"{code}") {{ success }} }}')
            self.assert_invalid(result, 'otp')

    def test_signin_rejects_blank_credentials(self):
        self.assert_invalid(self.execute('mutation { signin(username:"",password:"x") { accessToken } }'), 'username')
        self.assert_invalid(self.execute('mutation { signin(username:"synthetic-user",password:"") { accessToken } }'), 'password')


class GraphQLEndpointTests(StubbedCognitoTestCase):
    def test_http_endpoint_serves_the_schema(self):
        self.cognito.add_response('get_user', PROFILE, {'AccessToken': self.token})
        response = self.client.post(
            '/graphql',
            {'query': '{ getUser(username:"synthetic-user") { username } }'},
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'data': {'getUser': {'username': 'synthetic-user'}}})

    def test_unexpected_exceptions_are_masked_over_http(self):
        with patch('accounts.schema.verify_access_token', side_effect=RuntimeError('PRIVATE_STACK_DETAIL')), self.assertLogs('fitness_tracker.views', 'ERROR'):
            response = self.client.post(
                '/graphql',
                {'query': '{ getUser(username:"synthetic-user") { username } }'},
                content_type='application/json',
                HTTP_AUTHORIZATION=f'Bearer {self.token}',
            )
        body = response.json()
        self.assertEqual(body['errors'][0]['message'], 'Internal server error')
        self.assertNotIn('PRIVATE_STACK_DETAIL', response.content.decode())


class QueryLimitTests(StubbedCognitoTestCase):
    def post(self, query):
        return self.client.post('/graphql', {'query': query}, content_type='application/json').json()

    @override_settings(GRAPHQL_INTROSPECTION=False)
    def test_introspection_is_off_in_production(self):
        body = self.post('{ __schema { queryType { name } } }')
        self.assertIn('introspection is disabled', body['errors'][0]['message'])

    @override_settings(GRAPHQL_INTROSPECTION=False)
    def test_type_lookups_are_off_but_typename_still_works(self):
        self.assertIn('introspection is disabled', self.post('{ __type(name:"Query") { name } }')['errors'][0]['message'])
        self.assertEqual(self.post('{ __typename }'), {'data': {'__typename': 'Query'}})

    @override_settings(GRAPHQL_INTROSPECTION=True)
    def test_introspection_can_be_enabled_and_is_not_depth_limited(self):
        body = self.post('{ __schema { types { name fields { name type { name ofType { name ofType { name } } } } } } }')
        self.assertNotIn('errors', body)

    @override_settings(GRAPHQL_MAX_DEPTH=1)
    def test_queries_deeper_than_the_limit_are_refused(self):
        body = self.post(
            'mutation { signup(username:"synthetic-user",name:"Synthetic User",'
            'password:"offline-password",email:"synthetic@example.invalid") { user { username } } }'
        )
        self.assertIn('exceeds maximum operation depth', body['errors'][0]['message'])
        self.cognito.assert_no_pending_responses()
