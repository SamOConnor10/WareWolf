from django import template

register = template.Library()


@register.simple_tag
def elided_page_range(page_obj, on_each_side=3, on_ends=2):
    """Return elided page range for pagination (max ~10 visible numbers with ellipsis)."""
    paginator = page_obj.paginator
    return paginator.get_elided_page_range(
        number=page_obj.number,
        on_each_side=on_each_side,
        on_ends=on_ends,
    )


@register.simple_tag
def querystring(request, **kwargs):
    query = request.GET.copy()
    for key, value in kwargs.items():
        query[key] = value
    return query.urlencode()


@register.filter
def toggle_sort(current_sort, field):
    """Return the sort value for the next click: toggle asc/desc if same column, else asc."""
    if current_sort == field:
        return f"-{field}"
    if current_sort == f"-{field}":
        return field
    return field
