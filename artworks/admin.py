# artworks/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import Artwork, Comment, Transaction, GallerySetting, UserProfile
from django.utils.html import format_html # For displaying image in admin
from django.utils import timezone

class ArtworkAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'current_owner', 'is_for_sale_direct', 'direct_sale_price', 'is_for_auction', 'created_at')
    list_filter = ('is_for_sale_direct', 'is_for_auction', 'current_owner')
    search_fields = ('title', 'description', 'slug')
    prepopulated_fields = {'slug': ('title',)} # Auto-fills slug from title in admin form (client-side)

class CommentAdmin(admin.ModelAdmin):
    list_display = ('artwork', 'get_commenter_name', 'text_content_preview', 'created_at')
    list_filter = ('created_at', 'artwork')
    search_fields = ('text_content', 'guest_name', 'user__username')

    def get_commenter_name(self, obj):
        if obj.user:
            return obj.user.username
        return obj.guest_name or "Anonymous"
    get_commenter_name.short_description = 'Commenter' # Column header

    def text_content_preview(self, obj):
        return (obj.text_content[:75] + '...') if len(obj.text_content) > 75 else obj.text_content
    text_content_preview.short_description = 'Comment Preview'

class TransactionAdmin(admin.ModelAdmin):
    list_display = ('artwork_title', 'buyer_username', 'seller_username', 'final_price', 'status', 'initiated_at', 'dekont_preview')
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
            if artwork.current_owner != obj.buyer:
                artwork.current_owner = obj.buyer
                artwork.is_for_sale_direct = False
                artwork.direct_sale_price = None
                artwork.is_for_auction = False
                artwork.save()
            
            if not obj.admin_action_at:
                obj.admin_action_at = timezone.now()
                obj.save(update_fields=['admin_action_at'])
            # self.message_user(request, f"Transaction for '{artwork.title}' approved via form save and ownership transferred.", level=messages.SUCCESS)


    def approve_transactions(self, request, queryset):
        approved_count = 0
        for transaction in queryset:
            if transaction.status == 'pending_approval':
                artwork = transaction.artwork
                if artwork.current_owner != transaction.buyer:
                    artwork.current_owner = transaction.buyer
                    artwork.is_for_sale_direct = False
                    artwork.direct_sale_price = None
                    artwork.is_for_auction = False
                    artwork.save()

                transaction.status = 'approved'
                transaction.admin_action_at = timezone.now()
                transaction.save()
                approved_count += 1
        if approved_count > 0:
            self.message_user(request, f"{approved_count} transactions approved and ownerships transferred.")
        else:
            self.message_user(request, "No transactions were in 'pending_approval' state to approve.", level=messages.WARNING)
    approve_transactions.short_description = "Approve selected transactions"

    def reject_transactions(self, request, queryset):
        updated_count = 0
        for transaction in queryset:
            if transaction.status not in ['approved', 'rejected']:
                transaction.status = 'rejected'
                transaction.admin_action_at = timezone.now()
                transaction.save()
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

admin.site.unregister(User)
admin.site.register(User, UserAdmin)

admin.site.register(Artwork, ArtworkAdmin)
admin.site.register(Comment, CommentAdmin)
admin.site.register(Transaction, TransactionAdmin) # Make sure this line is present
admin.site.register(GallerySetting)
admin.site.register(UserProfile) # Optional, if you want a separate UserProfile list