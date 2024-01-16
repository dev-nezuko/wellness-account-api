from django.conf import settings
from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from fitness_tracker.views import AccountGraphQLView

urlpatterns = [
    path('graphql', csrf_exempt(AccountGraphQLView.as_view(graphiql=settings.DEBUG))),
]
