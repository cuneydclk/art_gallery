# artworks/urls.py
from django.urls import path
from . import views # Import views from the current app

app_name = 'artworks' # Namespace for URLs in this app

urlpatterns = [
    path('', views.artwork_list_view, name='artwork_list'), # Matches the root of the included path (e.g., /gallery/)
    path('art/<slug:slug>/', views.artwork_detail_view, name='artwork_detail'), # Matches /gallery/art/ANY_SLUG/
    path('art/<slug:artwork_slug>/register/', views.auction_register_view, name='auction_register'),
    path('art/<slug:artwork_slug>/manage-registrations/', views.manage_auction_registrations_view, name='manage_auction_registrations'),
    path('auctions/', views.available_auctions_view, name='available_auctions'),
    path('my-art/', views.my_art_view, name='my_art'),
    path('buy/initiate/<slug:artwork_slug>/', views.initiate_buy_view, name='initiate_buy'),
    path('transaction/<int:transaction_id>/payment/', views.payment_and_dekont_upload_view, name='payment_and_dekont_upload'),
    path('transaction/<int:transaction_id>/status/', views.transaction_status_view, name='transaction_status'),
    path('profile/edit/', views.edit_profile_view, name='edit_profile'),
]