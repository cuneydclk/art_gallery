# artworks/forms.py
from django import forms
from django.contrib.auth.models import User # Add User
from .models import Comment, Artwork, Transaction, UserProfile
from django.utils import timezone # Import timezone for validation

class CommentForm(forms.ModelForm):
    # We'll add the guest_name field conditionally in the view
    # or make it always visible but not required if user is logged in.
    # For now, let's make it simple.

    class Meta:
        model = Comment
        fields = ['text_content'] # Initially, only text_content for logged-in users
        widgets = {
            'text_content': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Write your comment here...'}),
        }

class GuestCommentForm(forms.ModelForm):
    guest_name = forms.CharField(max_length=100, required=True, label="Your Name", widget=forms.TextInput(attrs={'placeholder': 'Your Name'}))
    
    class Meta:
        model = Comment
        fields = ['guest_name', 'text_content']
        widgets = {
            'text_content': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Write your comment here...'}),
        }

class ArtworkDirectSaleForm(forms.ModelForm):
    class Meta:
        model = Artwork
        fields = ['is_for_sale_direct', 'direct_sale_price']
        widgets = {
            'direct_sale_price': forms.NumberInput(attrs={'step': '0.01', 'placeholder': 'e.g., 150.00'}),
        }
        labels = {
            'is_for_sale_direct': 'Offer for Direct Sale?',
            'direct_sale_price': 'Direct Sale Price ($)',
        }

    def clean(self):
        cleaned_data = super().clean()
        is_for_sale_direct = cleaned_data.get("is_for_sale_direct")
        direct_sale_price = cleaned_data.get("direct_sale_price")

        if is_for_sale_direct and (direct_sale_price is None or direct_sale_price <= 0):
            self.add_error('direct_sale_price', 'Price must be set and greater than zero if offering for direct sale.')
        
        if not is_for_sale_direct:
            # If not for sale, we can clear the price, or you can choose to keep it
            cleaned_data['direct_sale_price'] = None 

        # Ensure it's not also up for auction if setting for direct sale
        # We might handle this logic more explicitly later when implementing auction toggle
        # For now, let's assume they are mutually exclusive through UI/UX primarily
        
        return cleaned_data
    
class DekontUploadForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ['dekont_image']
        labels = {
            'dekont_image': 'Upload Dekont (PDF, JPG, PNG)'
        }
        help_texts = {
            'dekont_image': 'Please upload a clear image or PDF of your payment confirmation.'
        }
    
    def clean_dekont_image(self):
        dekont = self.cleaned_data.get('dekont_image', False)
        if dekont:
            if dekont.size > 5*1024*1024: # Max 5MB
                raise forms.ValidationError("File too large ( > 5MB )")
            # You can add more validation for file types here if needed
            # For example, check dekont.content_type
            return dekont
        else:
            raise forms.ValidationError("Couldn't read uploaded file.")
        
class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['bank_iban', 'bank_account_holder_name']
        labels = {
            'bank_iban': 'Your Bank IBAN (for payouts)',
            'bank_account_holder_name': 'Bank Account Holder Full Name',
        }
        
# --- NEW FORM FOR AUCTION SETTINGS ---
class ArtworkAuctionSettingsForm(forms.ModelForm):
    class Meta:
        model = Artwork
        fields = [
            'is_for_auction', 
            'auction_start_time', 
            'auction_scheduled_end_time', 
            'auction_minimum_bid', 
            'auction_signup_offset_minutes',
            # 'auction_status' # Status should be managed by logic, not direct user input here
        ]
        widgets = {
            'auction_start_time': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'auction_scheduled_end_time': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'auction_minimum_bid': forms.NumberInput(attrs={'step': '0.01', 'placeholder': 'e.g., 50.00'}),
            'auction_signup_offset_minutes': forms.NumberInput(attrs={'min': '0', 'placeholder': 'e.g., 30 (minutes)'}),
        }
        labels = {
            'is_for_auction': 'Offer this Artwork for Auction?',
            'auction_start_time': 'Auction Start Date & Time',
            'auction_scheduled_end_time': 'Scheduled Auction End Date & Time',
            'auction_minimum_bid': 'Minimum Starting Bid ($)',
            'auction_signup_offset_minutes': 'Sign-up Window Closes (minutes before start)',
        }
        help_texts = {
            'auction_start_time': 'When bidding officially begins.',
            'auction_scheduled_end_time': 'The planned end time. This can be extended by last-minute bids.',
            'auction_signup_offset_minutes': 'Example: If 30, sign-ups close 30 minutes before the auction_start_time.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make datetime fields use the HTML5 datetime-local input type
        self.fields['auction_start_time'].input_formats = ('%Y-%m-%dT%H:%M',)
        self.fields['auction_scheduled_end_time'].input_formats = ('%Y-%m-%dT%H:%M',)

    def clean(self):
        cleaned_data = super().clean()
        is_for_auction = cleaned_data.get("is_for_auction")
        start_time = cleaned_data.get("auction_start_time")
        end_time = cleaned_data.get("auction_scheduled_end_time")
        minimum_bid = cleaned_data.get("auction_minimum_bid")
        # signup_offset = cleaned_data.get("auction_signup_offset_minutes") # Already positive integer

        if is_for_auction:
            if not start_time:
                self.add_error('auction_start_time', 'Start time is required if offering for auction.')
            else:
                # Check if start time is in the past (allowing a small grace period for form submission lag)
                if start_time < (timezone.now() - timezone.timedelta(minutes=1)):
                    self.add_error('auction_start_time', 'Auction start time cannot be in the past.')

            if not end_time:
                self.add_error('auction_scheduled_end_time', 'Scheduled end time is required if offering for auction.')
            
            if start_time and end_time and end_time <= start_time:
                self.add_error('auction_scheduled_end_time', 'Scheduled end time must be after the start time.')
            
            if minimum_bid is None or minimum_bid <= 0:
                self.add_error('auction_minimum_bid', 'Minimum bid must be set and greater than zero.')
            
            # If is_for_auction is true, direct sale should be false.
            # This is better handled in the view or model's save to ensure consistency,
            # but we can reinforce it here if needed.
            # For now, we'll assume the view will set is_for_sale_direct = False if is_for_auction is True.

        else: # If not for auction, clear related fields
            cleaned_data['auction_start_time'] = None
            cleaned_data['auction_scheduled_end_time'] = None
            cleaned_data['auction_minimum_bid'] = None
            cleaned_data['auction_signup_offset_minutes'] = self.fields['auction_signup_offset_minutes'].initial or 30 # Reset to default
            # The model's save method also handles clearing these if is_for_auction is False

        return cleaned_data
    
