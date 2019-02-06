from django.conf.urls import url
from .views import main_view

urlpatterns = [
    # node main url entry
    url(r'^(?P<path>[a-zA-Z0-9-_/]+?)/$', main_view, name='pages_page_details'),
]
