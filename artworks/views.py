# artworks/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required # For restricting access
from .models import Artwork, Comment, Transaction, GallerySetting, UserProfile
from .forms import (CommentForm, GuestCommentForm, ArtworkDirectSaleForm, 
                    DekontUploadForm, UserProfileForm)
from django.contrib import messages
from django.utils import timezone # Import timezone for timestamps

def artwork_list_view(request):
    artworks = Artwork.objects.all().order_by('-created_at') # Get all artworks, newest first
    context = {
        'artworks': artworks,
        'page_title': 'Art Gallery'
    }
    return render(request, 'artworks/artwork_list.html', context)

def artwork_detail_view(request, slug):
    artwork = get_object_or_404(Artwork, slug=slug) # Get specific artwork by slug or return 404
    # We'll add comments and other details later
    context = {
        'artwork': artwork,
        'page_title': artwork.title
    }
    return render(request, 'artworks/artwork_detail.html', context)

def signup_view(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user) # Log the user in
            return redirect('artworks:artwork_list') # Redirect to gallery or user profile
    else:
        form = UserCreationForm()
    return render(request, 'registration/signup.html', {'form': form, 'page_title': 'Sign Up'})

@login_required  # This decorator restricts access to logged-in users only
def my_art_view(request):
    owned_artworks = Artwork.objects.filter(current_owner=request.user).order_by('-created_at')
    context = {
        'owned_artworks': owned_artworks,
        'page_title': 'My Art'
    }
    return render(request, 'artworks/my_art.html', context)


def artwork_detail_view(request, slug):
    artwork = get_object_or_404(Artwork, slug=slug)
    comments = artwork.comments.all().order_by('-created_at')
    
    # Initialize forms
    if request.user.is_authenticated:
        comment_form_initial = CommentForm()
    else:
        comment_form_initial = None # Will use guest_comment_form instead
    guest_comment_form_initial = GuestCommentForm()
    
    direct_sale_form_initial = None
    if request.user.is_authenticated and request.user == artwork.current_owner:
        direct_sale_form_initial = ArtworkDirectSaleForm(instance=artwork)

    if request.method == 'POST':
        # Check which form was submitted (we'll need a way to distinguish)
        # A simple way is to check for a unique button name/value or a hidden field.
        # For now, let's assume if 'is_for_sale_direct' is in POST, it's the sale form.

        if 'submit_comment' in request.POST: # Check for a specific button name
            if request.user.is_authenticated:
                comment_form = CommentForm(request.POST)
            else:
                comment_form = GuestCommentForm(request.POST) # Use the guest form name
            
            # Re-assign initial forms for context if this form is invalid
            guest_comment_form_to_render = guest_comment_form_initial if request.user.is_authenticated else comment_form
            comment_form_to_render = comment_form if request.user.is_authenticated else comment_form_initial

            if comment_form.is_valid():
                new_comment = comment_form.save(commit=False)
                new_comment.artwork = artwork
                if request.user.is_authenticated:
                    new_comment.user = request.user
                new_comment.save()
                messages.success(request, 'Your comment has been posted!')
                return redirect('artworks:artwork_detail', slug=artwork.slug)
            else:
                messages.error(request, 'There was an error posting your comment.')
                # The forms with errors will be passed to context below

        elif 'submit_sale_settings' in request.POST and request.user.is_authenticated and request.user == artwork.current_owner:
            direct_sale_form = ArtworkDirectSaleForm(request.POST, instance=artwork)
            if direct_sale_form.is_valid():
                updated_artwork = direct_sale_form.save(commit=False)
                if updated_artwork.is_for_sale_direct:
                    updated_artwork.is_for_auction = False # Mutually exclusive for now
                    # updated_artwork.auction_start_time = None
                    # updated_artwork.auction_end_time = None
                updated_artwork.save()
                messages.success(request, 'Sale settings updated successfully!')
                return redirect('artworks:artwork_detail', slug=artwork.slug)
            else:
                messages.error(request, 'Error updating sale settings.')
                direct_sale_form_initial = direct_sale_form # Pass form with errors
            
            # Ensure comment forms are set to their initial state if sale form was processed
            comment_form_to_render = comment_form_initial
            guest_comment_form_to_render = guest_comment_form_initial


        # Determine which forms to pass to the template after POST processing
        # If a form was processed and had errors, direct_sale_form_initial or comment_form/guest_comment_form might be updated
        # Default to initial forms if not processed or successfully processed
        final_comment_form = comment_form_to_render if 'comment_form_to_render' in locals() else comment_form_initial
        final_guest_comment_form = guest_comment_form_to_render if 'guest_comment_form_to_render' in locals() else guest_comment_form_initial
        final_direct_sale_form = direct_sale_form_initial # This will be the form with errors if sale settings update failed, or the initial one

    else: # GET request
        final_comment_form = comment_form_initial
        final_guest_comment_form = guest_comment_form_initial
        final_direct_sale_form = direct_sale_form_initial


    context = {
        'artwork': artwork,
        'comments': comments,
        'comment_form': final_comment_form,
        'guest_comment_form': final_guest_comment_form,
        'direct_sale_form': final_direct_sale_form, # Pass the sale form
        'page_title': artwork.title
    }
    return render(request, 'artworks/artwork_detail.html', context)

@login_required
def initiate_buy_view(request, artwork_slug):
    artwork = get_object_or_404(Artwork, slug=artwork_slug)

    # Ensure artwork is for sale and user is not the owner
    if not artwork.is_for_sale_direct or not artwork.direct_sale_price:
        messages.error(request, "This artwork is not currently for direct sale.")
        return redirect('artworks:artwork_detail', slug=artwork.slug)
    
    if artwork.current_owner == request.user:
        messages.error(request, "You cannot buy your own artwork.")
        return redirect('artworks:artwork_detail', slug=artwork.slug)

    # Check if there's an existing pending transaction for this user and artwork
    existing_transaction = Transaction.objects.filter(
        artwork=artwork, 
        buyer=request.user, 
        status__in=['pending_payment', 'pending_approval']
    ).first()

    if existing_transaction:
        messages.info(request, "You already have a pending purchase for this artwork.")
        return redirect('artworks:payment_and_dekont_upload', transaction_id=existing_transaction.id)


    if request.method == 'POST': # Ensure it's a POST request from the "Buy Now" button
        transaction = Transaction.objects.create(
            artwork=artwork,
            buyer=request.user,
            seller=artwork.current_owner, # Owner at the time of sale
            sale_type='direct_buy',
            final_price=artwork.direct_sale_price,
            status='pending_payment'
        )
        # Optionally, mark the artwork as "reserved" or temporarily not for sale
        # artwork.is_for_sale_direct = False # Or add a new status like 'reserved'
        # artwork.save()
        messages.success(request, f"Purchase initiated for '{artwork.title}'. Please proceed with payment and dekont upload.")
        return redirect('artworks:payment_and_dekont_upload', transaction_id=transaction.id) # New URL
    
    # If GET request to this URL, redirect back or show error
    messages.error(request, "Invalid request method for initiating purchase.")
    return redirect('artworks:artwork_detail', slug=artwork.slug)


@login_required
def payment_and_dekont_upload_view(request, transaction_id):
    transaction = get_object_or_404(Transaction, id=transaction_id, buyer=request.user)

    # Ensure transaction is in a state where dekont can be uploaded
    if transaction.status not in ['pending_payment', 'pending_approval']: # Allow re-upload if pending_approval
        messages.error(request, "This transaction is not awaiting payment or dekont upload.")
        # Redirect to a user's transaction history page or profile later
        return redirect('artworks:artwork_detail', slug=transaction.artwork.slug) 

    gallery_settings = GallerySetting.load() # Or hardcode if not using model

    if request.method == 'POST':
        form = DekontUploadForm(request.POST, request.FILES, instance=transaction)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.status = 'pending_approval'
            transaction.dekont_uploaded_at = timezone.now()
            transaction.save()
            messages.success(request, "Dekont uploaded successfully. We will review it shortly.")
            return redirect('artworks:transaction_status', transaction_id=transaction.id) # New "status" page
    else:
        form = DekontUploadForm(instance=transaction) # Pre-fill if re-uploading

    context = {
        'transaction': transaction,
        'artwork': transaction.artwork,
        'form': form,
        'gallery_settings': gallery_settings,
        'page_title': f"Payment for {transaction.artwork.title}"
    }
    return render(request, 'artworks/payment_dekont_upload.html', context)

@login_required
def transaction_status_view(request, transaction_id):
    transaction = get_object_or_404(Transaction, id=transaction_id, buyer=request.user)
    context = {
        'transaction': transaction,
        'artwork': transaction.artwork,
        'page_title': f"Transaction Status for {transaction.artwork.title}"
    }
    return render(request, 'artworks/transaction_status.html', context)


@login_required
def edit_profile_view(request):
    try:
        profile = request.user.profile
    except UserProfile.DoesNotExist:
        # This should ideally not happen due to the signal, but as a fallback:
        profile = UserProfile.objects.create(user=request.user)
        
    if request.method == 'POST':
        form = UserProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your profile has been updated successfully.')
            return redirect('artworks:edit_profile') # Or to a general profile page
    else:
        form = UserProfileForm(instance=profile)

    context = {
        'form': form,
        'page_title': 'Edit Your Profile & Bank Details'
    }
    return render(request, 'artworks/edit_profile.html', context)

