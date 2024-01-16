import logging

from django.conf import settings
from graphene.validation import depth_limit_validator
from graphene_django.views import GraphQLView
from graphql import GraphQLError, ValidationRule

logger = logging.getLogger(__name__)


class DisableSchemaIntrospection(ValidationRule):
    # graphene's DisableIntrospection also rejects __typename, which Apollo and
    # Relay clients add to every selection; only the schema queries are blocked.
    def enter_field(self, node, *_args):
        if node.name.value in ('__schema', '__type'):
            self.report_error(GraphQLError(f"Cannot query '{node.name.value}': introspection is disabled.", node))


class AccountGraphQLView(GraphQLView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Introspection fields don't count towards the depth, so GraphiQL keeps working.
        rules = [depth_limit_validator(max_depth=settings.GRAPHQL_MAX_DEPTH)]
        if not settings.GRAPHQL_INTROSPECTION:
            rules.append(DisableSchemaIntrospection)
        self.validation_rules = tuple(rules)

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
