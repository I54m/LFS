from django import template

register = template.Library()

@register.filter
def print_file_content(f):
    try:
        return f.read()
    except IOError:
        return ''