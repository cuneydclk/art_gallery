# artworks/models.py
from django.db import models
from django.contrib.auth.models import User # To link to the owner
from django.utils.text import slugify # For generating slugs
from django.utils import timezone
from django.db.models.signals import post_save # For auto-creating profile
from django.dispatch import receiver # For auto-creating profile

class Artwork(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=255, unique=True, blank=True, help_text="Unique URL-friendly identifier. Leave blank to auto-generate from title.")
    description = models.TextField()
    # For now, we'll use a CharField for a placeholder image URL.
    # We will upgrade this to an ImageField later for actual uploads.
    image_placeholder_url = models.URLField(max_length=500, blank=True, null=True, help_text="URL to a placeholder image for now.")
    
    # Ownership
    current_owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="owned_artworks")
    
    # Sale Status
    is_for_sale_direct = models.BooleanField(default=False)
    direct_sale_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    is_for_auction = models.BooleanField(default=False)
    auction_start_time = models.DateTimeField(null=True, blank=True)
    auction_end_time = models.DateTimeField(null=True, blank=True)
    auction_minimum_bid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    auction_current_highest_bid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    auction_current_highest_bidder = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="current_bids_on")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug: # If slug is not provided
            self.slug = slugify(self.title)
            # Ensure slug uniqueness if multiple artworks have similar titles
            original_slug = self.slug
            counter = 1
            while Artwork.objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
                self.slug = f'{original_slug}-{counter}'
                counter += 1
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-created_at'] # Default ordering for queries

class Comment(models.Model):
    artwork = models.ForeignKey(Artwork, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, help_text="Registered user who commented, if any.")
    guest_name = models.CharField(max_length=100, blank=True, null=True, help_text="Name of the guest commenter, if not a registered user.")
    text_content = models.TextField()
    created_at = models.DateTimeField(default=timezone.now) # Use timezone.now for default

    def __str__(self):
        if self.user:
            return f"Comment by {self.user.username} on {self.artwork.title}"
        elif self.guest_name:
            return f"Comment by {self.guest_name} (Guest) on {self.artwork.title}"
        else:
            return f"Anonymous comment on {self.artwork.title}"

    class Meta:
        ordering = ['created_at'] # Show oldest comments first, or '-created_at' for newest first

class Transaction(models.Model):
    TRANSACTION_STATUS_CHOICES = [
        ('pending_payment', 'Pending Payment'), # Buyer initiated, waiting for dekont
        ('pending_approval', 'Pending Approval'), # Dekont uploaded, waiting for admin
        ('approved', 'Approved'),               # Admin approved, ownership transferred
        ('rejected', 'Rejected'),               # Admin rejected
        ('cancelled', 'Cancelled'),             # Buyer cancelled before payment (optional)
    ]
    SALE_TYPE_CHOICES = [
        ('direct_buy', 'Direct Buy'),
        ('auction_win', 'Auction Win'),
    ]

    artwork = models.ForeignKey(Artwork, on_delete=models.PROTECT, related_name='transactions') # Protect so artwork isn't deleted if a transaction exists
    buyer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='purchases')
    seller = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='sales_made') # Stores the owner at the time of sale initiation

    sale_type = models.CharField(max_length=20, choices=SALE_TYPE_CHOICES)
    final_price = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Dekont / Proof of Payment
    dekont_image = models.FileField(upload_to='dekonts/', null=True, blank=True) # We'll handle file uploads properly later
    
    status = models.CharField(max_length=20, choices=TRANSACTION_STATUS_CHOICES, default='pending_payment')
    
    initiated_at = models.DateTimeField(auto_now_add=True) # When buyer clicked "Buy Now"
    dekont_uploaded_at = models.DateTimeField(null=True, blank=True)
    admin_action_at = models.DateTimeField(null=True, blank=True)
    admin_remarks = models.TextField(blank=True, null=True, help_text="Reason for rejection, or other notes.")

    def __str__(self):
        return f"Transaction for {self.artwork.title} by {self.buyer.username if self.buyer else 'N/A'} - Status: {self.get_status_display()}"

    class Meta:
        ordering = ['-initiated_at']

class GallerySetting(models.Model): # Singleton model pattern
    bank_account_iban = models.CharField(max_length=100, default="TR33 0006 1005 1978 6457 8413 26")
    bank_account_holder = models.CharField(max_length=200, default="Art Gallery İzmir")
    contact_phone = models.CharField(max_length=20, default="+90 555 555 5555")
    payment_instructions = models.TextField(blank=True, help_text="Additional instructions for payment, e.g., reference number format.")

    def __str__(self):
        return "Gallery Payment Settings"

    def save(self, *args, **kwargs): # Enforce singleton
        self.pk = 1
        super(GallerySetting, self).save(*args, **kwargs)

    def delete(self, *args, **kwargs): # Prevent deletion
        pass

    @classmethod
    def load(cls): # Convenience method to get the settings object
        obj, created = cls.objects.get_or_create(pk=1)
        return obj
    
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    bank_iban = models.CharField(max_length=100, blank=True, null=True, help_text="Your IBAN for receiving payments.")
    bank_account_holder_name = models.CharField(max_length=200, blank=True, null=True, help_text="Full name as on bank account.")
    # Add other profile fields if needed, e.g., phone, address

    def __str__(self):
        return f"{self.user.username}'s Profile"

# Signal to create or update UserProfile whenever a User instance is saved.
@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)
    instance.profile.save() # Ensures profile is saved even if user is just updated

