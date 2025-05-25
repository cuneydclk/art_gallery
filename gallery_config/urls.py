# gallery_config/urls.py
from django.contrib import admin
from django.urls import path, include
from artworks import views as artwork_views
from django.views.generic import TemplateView
from django.conf import settings # Add this
from django.conf.urls.static import static # Add this

urlpatterns = [
    path('', TemplateView.as_view(template_name='home.html'), name='home'), # Homepage
    path('admin/', admin.site.urls),
    path('gallery/', include(('artworks.urls', 'artworks'), namespace='artworks')),
    path('accounts/signup/', artwork_views.signup_view, name='signup'),
    path('accounts/', include('django.contrib.auth.urls')),
]

# Serve media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)