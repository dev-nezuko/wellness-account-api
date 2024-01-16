import logging

from django.conf import settings
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from graphene.validation import depth_limit_validator
from graphene_django.views import GraphQLView
from graphql import GraphQLError, ValidationRule

logger = logging.getLogger(__name__)

# Browsers can only send these cross-site after a CORS preflight, which the
# CORS_ALLOWED_ORIGINS allowlist answers. Form and text/plain bodies need no
# preflight, so they are refused rather than CSRF-exempted.
PREFLIGHTED_BODY_TYPES = {'application/json', 'application/graphql'}


class DisableSchemaIntrospection(ValidationRule):
    # graphene's DisableIntrospection also rejects __typename, which Apollo and
    # Relay clients add to every selection; only the schema queries are blocked.
    def enter_field(self, node, *_args):
        if node.name.value in ('__schema', '__type'):
            self.report_error(GraphQLError(f"Cannot query '{node.name.value}': introspection is disabled.", node))


@method_decorator(csrf_exempt, name='dispatch')
class AccountGraphQLView(GraphQLView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Introspection fields don't count towards the depth, so GraphiQL keeps working.
        rules = [depth_limit_validator(max_depth=settings.GRAPHQL_MAX_DEPTH)]
        if not settings.GRAPHQL_INTROSPECTION:
            rules.append(DisableSchemaIntrospection)
        self.validation_rules = tuple(rules)

    def dispatch(self, request, *args, **kwargs):
        if request.method == 'POST' and self.get_content_type(request) not in PREFLIGHTED_BODY_TYPES:
            return JsonResponse({'errors': [{'message': 'Send GraphQL requests as application/json'}]}, status=415)
        return super().dispatch(request, *args, **kwargs)

    @staticmethod
    def format_error(error):
        formatted = GraphQLView.format_error(error)
        original = getattr(error, 'original_error', None)
        # Resolvers raise GraphQLError with client-safe text on purpose. Anything
        # else is a bug whose message may hold internals, so log it and hide it.
        if original is not None and not isinstance(original, GraphQLError):
            logger.error('Unhandled error while resolving %s', getattr(error, 'path', None), exc_info=original)
            formatted['message'] = 'Internal server error'
        return formatted
