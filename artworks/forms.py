# artworks/forms.py
from django import forms
from django.contrib.auth.models import User # Add User
from .models import Comment, Artwork, Transaction, UserProfile

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
        
