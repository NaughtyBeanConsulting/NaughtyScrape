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
def get_item(d, key):
    if hasattr(d, "get"):
        return d.get(key)
    return None
