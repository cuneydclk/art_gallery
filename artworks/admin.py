# artworks/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
# Ensure all new models are imported
from .models import (Artwork, Comment, Transaction, GallerySetting, UserProfile, 
                     AuctionRegistration, Bid) # Added AuctionRegistration, Bid
from django.utils.html import format_html
from django.utils import timezone
from django.contrib import messages


class ArtworkAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'slug', 'current_owner', 
        'is_for_sale_direct', 'direct_sale_price', 
        'is_for_auction', 'auction_status', 'auction_start_time', 
        'created_at'
    )
    list_filter = ('is_for_sale_direct', 'is_for_auction', 'auction_status', 'current_owner')
    search_fields = ('title', 'description', 'slug')
    prepopulated_fields = {'slug': ('title',)}
    
    fieldsets = (
        (None, {'fields': ('title', 'slug', 'description', 'image_placeholder_url', 'current_owner')}),
        ('Direct Sale', {'fields': ('is_for_sale_direct', 'direct_sale_price'), 'classes': ('collapse',)}),
        ('Auction Settings', {'fields': (
            'is_for_auction', 'auction_status',
            'auction_start_time', 'auction_scheduled_end_time', 'auction_minimum_bid',
            'auction_signup_offset_minutes', 'auction_signup_deadline',
        ), 'classes': ('collapse',)}),
        ('Current Auction State (System Managed)', {'fields': ( # Renamed section slightly
            'auction_current_highest_bid', 'auction_current_highest_bidder',
            'last_bid_time',
            # REMOVED: 'auction_winner', 'auction_winning_price' from here
        ), 'classes': ('collapse',)}),
    )

    readonly_fields = (
        'auction_signup_deadline',
        'auction_current_highest_bid', 'auction_current_highest_bidder',
        'last_bid_time',
        # REMOVED: 'auction_winner', 'auction_winning_price' from here
    )


class CommentAdmin(admin.ModelAdmin):
    list_display = ('artwork', 'get_commenter_name', 'text_content_preview', 'created_at')
    list_filter = ('created_at', 'artwork')
    search_fields = ('text_content', 'guest_name', 'user__username')

    def get_commenter_name(self, obj):
        if obj.user:
            return obj.user.username
        return obj.guest_name or "Anonymous"
    get_commenter_name.short_description = 'Commenter'

    def text_content_preview(self, obj):
        return (obj.text_content[:75] + '...') if len(obj.text_content) > 75 else obj.text_content
    text_content_preview.short_description = 'Comment Preview'

class TransactionAdmin(admin.ModelAdmin):
    list_display = ('artwork_title', 'buyer_username', 'seller_username', 'final_price', 'sale_type', 'status', 'initiated_at', 'dekont_preview') # Added sale_type
    list_filter = ('status', 'sale_type', 'initiated_at')
    search_fields = ('artwork__title', 'buyer__username', 'seller__username')
    readonly_fields = ('initiated_at', 'dekont_uploaded_at', 'admin_action_at', 'dekont_image_display', 'seller')
    
    fields = (('artwork', 'buyer'), ('seller'), ('sale_type', 'final_price'), 'status', 'admin_remarks', 'dekont_image', 'dekont_image_display', 'initiated_at', 'dekont_uploaded_at', 'admin_action_at')

    def artwork_title(self, obj):
        return obj.artwork.title
    artwork_title.short_description = 'Artwork'

    def buyer_username(self, obj):
        return obj.buyer.username if obj.buyer else "N/A"
    buyer_username.short_description = 'Buyer'

    def seller_username(self, obj):
        return obj.seller.username if obj.seller else "N/A"
    seller_username.short_description = 'Seller'
    
    def dekont_preview(self, obj):
        if obj.dekont_image:
            return format_html('<a href="{}">View Dekont</a>', obj.dekont_image.url)
        return "No Dekont"
    dekont_preview.short_description = 'Dekont'

    def dekont_image_display(self, obj):
        if obj.dekont_image:
            return format_html('<img src="{}" width="150" height="auto" /> <br/> <a href="{}">Full Image</a>', obj.dekont_image.url, obj.dekont_image.url)
        return "No dekont uploaded."
    dekont_image_display.short_description = 'Dekont Preview'

    def save_model(self, request, obj, form, change):
        original_status = None
        if obj.pk:
            try:
                original_status = Transaction.objects.get(pk=obj.pk).status
            except Transaction.DoesNotExist:
                pass

        super().save_model(request, obj, form, change)

        if obj.status == 'approved' and original_status != 'approved':
            artwork = obj.artwork
            if artwork.current_owner != obj.buyer and obj.buyer: # Ensure buyer is set
                artwork.current_owner = obj.buyer
                # Reset sale flags
                artwork.is_for_sale_direct = False
                artwork.direct_sale_price = None
                
                if obj.sale_type == 'auction_win':
                    artwork.is_for_auction = False 
                    artwork.auction_status = 'completed' # Mark auction as completed
                    # auction_winner and auction_winning_price should have been set on the Artwork
                    # when the auction ended and transaction was created.
                    # No need to set them here again directly from transaction.
                
                artwork.save()
            
            if not obj.admin_action_at:
                obj.admin_action_at = timezone.now()
                obj.save(update_fields=['admin_action_at'])


    def approve_transactions(self, request, queryset):
        approved_count = 0
        for transaction in queryset:
            if transaction.status == 'pending_approval' and transaction.buyer: # Ensure buyer is set
                artwork = transaction.artwork
                if artwork.current_owner != transaction.buyer:
                    artwork.current_owner = transaction.buyer
                    artwork.is_for_sale_direct = False
                    artwork.direct_sale_price = None

                    if transaction.sale_type == 'auction_win':
                        artwork.is_for_auction = False
                        artwork.auction_status = 'completed'
                    
                    artwork.save()

                transaction.status = 'approved'
                transaction.admin_action_at = timezone.now()
                transaction.save()
                approved_count += 1
        if approved_count > 0:
            self.message_user(request, f"{approved_count} transactions approved and ownerships transferred.")
        else:
            self.message_user(request, "No transactions were in 'pending_approval' state or had a buyer to approve.", level=messages.WARNING)
    approve_transactions.short_description = "Approve selected transactions"

    def reject_transactions(self, request, queryset):
        updated_count = 0
        for transaction in queryset:
            if transaction.status not in ['approved', 'rejected']:
                transaction.status = 'rejected'
                transaction.admin_action_at = timezone.now()
                transaction.save()

                # If an auction payment is rejected
                if transaction.sale_type == 'auction_win':
                    artwork = transaction.artwork
                    artwork.auction_status = 'failed_payment'
                    # Potentially reset auction_winner if you want the slot open for a second chance offer later
                    # artwork.auction_winner = None 
                    # artwork.auction_winning_price = None
                    artwork.save(update_fields=['auction_status']) # Only update auction_status

                updated_count +=1
        if updated_count > 0:
            self.message_user(request, f"{updated_count} transactions rejected.")
        else:
             self.message_user(request, "No transactions were in a state to be rejected.", level=messages.WARNING)
    
    actions = [approve_transactions, reject_transactions]


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Profile Info (Bank Details, etc.)'
    fields = ('bank_iban', 'bank_account_holder_name')

class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)

# --- ADMIN REGISTRATIONS FOR NEW MODELS ---
@admin.register(AuctionRegistration)
class AuctionRegistrationAdmin(admin.ModelAdmin):
    list_display = ('artwork', 'user', 'status', 'registered_at', 'owner_reviewed_at')
    list_filter = ('status', 'artwork__title', 'user__username', 'artwork__auction_status')
    search_fields = ('artwork__title', 'user__username')
    readonly_fields = ('registered_at', 'owner_reviewed_at') # owner_reviewed_at set by actions
    # Allow admin to change status via list_editable or actions
    list_editable = ('status',) 
    actions = ['approve_registrations', 'reject_registrations']

    def approve_registrations(self, request, queryset):
        updated_count = queryset.update(status='approved', owner_reviewed_at=timezone.now())
        self.message_user(request, f'{updated_count} registrations approved.')
    approve_registrations.short_description = "Approve selected registrations"

    def reject_registrations(self, request, queryset):
        updated_count = queryset.update(status='rejected', owner_reviewed_at=timezone.now())
        self.message_user(request, f'{updated_count} registrations rejected.')
    reject_registrations.short_description = "Reject selected registrations"


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ('artwork', 'bidder', 'amount', 'timestamp')
    list_filter = ('artwork__title', 'bidder__username', 'timestamp')
    search_fields = ('artwork__title', 'bidder__username')
    readonly_fields = ('timestamp',)


admin.site.unregister(User)
admin.site.register(User, UserAdmin)

admin.site.register(Artwork, ArtworkAdmin)
admin.site.register(Comment, CommentAdmin)
admin.site.register(Transaction, TransactionAdmin)
admin.site.register(GallerySetting)
admin.site.register(UserProfile)
# AuctionRegistration and Bid are registered using @admin.register decorator above