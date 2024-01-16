import logging

from graphene_django.views import GraphQLView
from graphql import GraphQLError

logger = logging.getLogger(__name__)


class AccountGraphQLView(GraphQLView):
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
