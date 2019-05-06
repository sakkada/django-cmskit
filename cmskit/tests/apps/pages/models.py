"""
1. Model inheritance
2. Tree Model
3. Page Model


MSTI model                  To be allowed:      Item(MSTIModel)
MSTI manager                                        objects = MSTI manager
MSTI queryset
MSTI metaclass

Tree model
Tree manager
Tree queryset
Tree metaclass

Page model
Page manager
Page queryset
Page metaclass
"""

from django.db import models
from django.utils.translation import ugettext_lazy as _
from cmskit.models import BasePage
from cmskit.contrib.items.models import BaseItemPage, BaseItem


class Page(BasePage):

    class Meta:
        verbose_name = _('Page')
        verbose_name_plural = _('Pages')


class MTIPage(Page):
    alt_title = models.CharField(verbose_name=_('alt_title'), max_length=255)

    class Meta:
        verbose_name = _('MTI page')
        verbose_name_plural = _('MTI pages')


class MMTIPage(MTIPage):
    alt2_title = models.CharField(verbose_name=_('alt2_title'), max_length=255)
    class Meta:
        verbose_name = _('MMTI page')
        verbose_name_plural = _('MMTI pages')


class STIPage(Page):
    unique = '123456'
    class Meta:
        proxy = True
        verbose_name = _('STI page')
        verbose_name_plural = _('STI pages')
    subpage_types = (
        'pages.mtipage',
    )


class SSTIPage(STIPage):
    unique2 = '123456'
    class Meta:
        proxy = True
        verbose_name = _('SSTI page')
        verbose_name_plural = _('SSTI pages')




class ItemPage(BaseItemPage, Page):
    pass


class Item(BaseItem):
    page = models.ForeignKey(
        ItemPage, related_name='items', on_delete=models.CASCADE,
        help_text=_('Parent page.'))




class Page2(BasePage):

    class Meta:
        verbose_name = _('Page 2')
        verbose_name_plural = _('Pages 2')




class InlineModel(models.Model):
    page = models.ForeignKey(Page, on_delete=models.CASCADE)
    title = models.CharField(verbose_name=_('title'), max_length=255)


class TIInlineModel(models.Model):
    page = models.ForeignKey(MTIPage, on_delete=models.CASCADE)
    title = models.CharField(verbose_name=_('title'), max_length=255)



TEMPLATES = (
    {
        'name': 'base',
        'path': 'base.html',
        'title': _('General site template'),
        'areas': (
            ('header', _('Page header')),
            ('sidebar', _('Sidebar'),),
        ),
    }, {
        'name': 'index',
        'path': 'index.html',
        'title': _('Intex template'),
        'areas': (
            ('header', _('Page header')),
        ),
    }
)
