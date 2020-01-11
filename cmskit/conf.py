from django.conf import settings
from django.utils.translation import gettext_lazy as _


"""
cmskit sample settings
CMSKIT_TEMPLATES = (
    {
        'name': 'base',                         # required
        'path': 'base.html',                    # required
        'title': _('General site template'),
        'areas': (
            ('header', _('Page header')),
            ('sidebar', _('Sidebar'),),
        ),
    }, {
        'name': 'index',                        # required
        'path': 'index.html',                   # required
        'title': _('Intex template'),
        'areas': (
            ('header', _('Page header')),
        ),
    }
)
"""


DEFAULT_TEMPLATES = (
    {
        'code': 'base',                         # required
        'path': 'base.html',                    # required
        'name': _('General site template'),
    },
)

TEMPLATES = getattr(settings, 'CMSKIT_TEMPLATES', DEFAULT_TEMPLATES)
