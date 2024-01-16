from django.conf import settings
from django.urls import path

from fitness_tracker.views import AccountGraphQLView

urlpatterns = [
    path('graphql', AccountGraphQLView.as_view(graphiql=settings.DEBUG)),
]
