# artworks/templatetags/artwork_extras.py
from django import template
from django.utils.translation import ngettext_lazy, gettext_lazy as _

register = template.Library()

@register.filter
def humanize_timedelta(timedelta_obj):
    if timedelta_obj is None:
        return ""

    days = timedelta_obj.days
    seconds = timedelta_obj.seconds
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    
    parts = []
    if days > 0:
        parts.append(ngettext_lazy("%(count)d day", "%(count)d days", days) % {'count': days})
    if hours > 0:
        parts.append(ngettext_lazy("%(count)d hour", "%(count)d hours", hours) % {'count': hours})
    if minutes > 0:
        parts.append(ngettext_lazy("%(count)d minute", "%(count)d minutes", minutes) % {'count': minutes})
    
    if not parts: # If less than a minute
        if timedelta_obj.total_seconds() > 0:
            return _("less than a minute")
        else: # If it's zero or negative, though our view logic should prevent negative.
            return _("now") 
    
    return ", ".join(str(p) for p in parts) # Ensure parts are strings for join