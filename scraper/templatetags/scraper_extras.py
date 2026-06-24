from django import template

register = template.Library()

LEAD_STATUS_CLASSES = {
    "new": "bg-sky-100 text-sky-700",
    "contacted": "bg-amber-100 text-amber-700",
    "qualified": "bg-violet-100 text-violet-700",
    "won": "bg-emerald-100 text-emerald-700",
    "lost": "bg-rose-100 text-rose-700",
    "not_a_fit": "bg-gray-100 text-gray-600",
}

JOB_STATUS_CLASSES = {
    "pending": "bg-gray-100 text-gray-600",
    "running": "bg-blue-100 text-blue-700",
    "done": "bg-emerald-100 text-emerald-700",
    "failed": "bg-rose-100 text-rose-700",
    "cancelled": "bg-amber-100 text-amber-700",
}

ENRICHMENT_CLASSES = {
    "none": "bg-gray-100 text-gray-500",
    "pending": "bg-blue-100 text-blue-700",
    "done": "bg-emerald-100 text-emerald-700",
    "failed": "bg-rose-100 text-rose-700",
    "no_website": "bg-gray-100 text-gray-400",
}

LOG_LEVEL_CLASSES = {
    "info": "text-gray-600",
    "warning": "text-amber-600",
    "error": "text-rose-600",
}

ACTIVITY_ICONS = {
    "note": "📝",
    "call": "📞",
    "email": "✉️",
    "whatsapp": "💬",
    "meeting": "🤝",
    "status": "🏷️",
    "assignment": "👤",
    "tag": "🔖",
    "task": "✅",
    "contact": "👥",
    "system": "⚙️",
}

ACTIVITY_DOT_CLASSES = {
    "note": "bg-stone-400",
    "call": "bg-sky-500",
    "email": "bg-indigo-500",
    "whatsapp": "bg-emerald-500",
    "meeting": "bg-violet-500",
    "status": "bg-amber-500",
    "assignment": "bg-blue-500",
    "tag": "bg-teal-500",
    "task": "bg-emerald-600",
    "contact": "bg-fuchsia-500",
    "system": "bg-gray-300",
}

# Tag colour name -> badge classes. Names are safelisted in tailwind.config.js.
TAG_COLOR_CLASSES = {
    "stone": "bg-stone-100 text-stone-700",
    "amber": "bg-amber-100 text-amber-700",
    "sky": "bg-sky-100 text-sky-700",
    "emerald": "bg-emerald-100 text-emerald-700",
    "violet": "bg-violet-100 text-violet-700",
    "rose": "bg-rose-100 text-rose-700",
    "blue": "bg-blue-100 text-blue-700",
    "teal": "bg-teal-100 text-teal-700",
}


@register.filter
def lead_status_classes(value):
    return LEAD_STATUS_CLASSES.get(value, "bg-gray-100 text-gray-600")


@register.filter
def job_status_classes(value):
    return JOB_STATUS_CLASSES.get(value, "bg-gray-100 text-gray-600")


@register.filter
def enrichment_classes(value):
    return ENRICHMENT_CLASSES.get(value, "bg-gray-100 text-gray-500")


@register.filter
def log_level_classes(value):
    return LOG_LEVEL_CLASSES.get(value, "text-gray-600")


@register.filter
def activity_icon(value):
    return ACTIVITY_ICONS.get(value, "•")


@register.filter
def activity_dot_classes(value):
    return ACTIVITY_DOT_CLASSES.get(value, "bg-stone-400")


@register.filter
def tag_color_classes(value):
    return TAG_COLOR_CLASSES.get(value, "bg-stone-100 text-stone-700")


@register.filter
def initials(user):
    """Compact avatar text for a user (first+last initial, else email start)."""
    if not user:
        return "—"
    first = (getattr(user, "first_name", "") or "").strip()
    last = (getattr(user, "last_name", "") or "").strip()
    if first or last:
        return ((first[:1] + last[:1]) or first[:2]).upper()
    return (getattr(user, "email", "?") or "?")[:2].upper()


@register.filter
def get_item(d, key):
    if hasattr(d, "get"):
        return d.get(key)
    return None
