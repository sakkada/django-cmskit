from django.utils.translation import ugettext_lazy as _
from django.urls import reverse
from django.contrib import admin
from django.db import models
from django import forms
from cmskit.admin import BasePageAdmin
from cmskit.utils.admin import FieldsetsDictMixin


class BaseItemPageAdmin(BasePageAdmin):
    fieldsets_dict = {
        'behaviour': {
            'title': _('Behaviour settings'),
            'classes': ('collapse',),
            'fields': (
                'behaviour', 'alt_template', 'alt_view',
                'filter', 'filter_date', 'order_by', 'onpage',
            ),
        },
    }


class BaseItemAdmin(FieldsetsDictMixin, admin.ModelAdmin):
    list_display = (
        'title', 'id', 'slug', 'weight', 'page', 'active', 'published',)
    list_filter = ('page', 'date_create',)
    ordering = ('-date_start', '-weight',)
    search_fields = ('title',)
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = ('active', 'date_create', 'date_update',)
    fieldsets_dict = {
        'main': {
            'fields': (
                ('date_start', 'date_end',), 'title', ('weight', 'published',),
            ),
        },
        'path': {
            'title': _('Path and node settings'),
            'fields': ('slug', 'url', 'page',),
        },
        'behaviour': {
            'title': _('Behaviour settings'),
            'classes': ('collapse',),
            'fields': (
                'alt_template', 'alt_view', 'visible', 'show_item_name',
                'show_node_link', 'show_in_meta',
            ),
        },
        'readonly': {
            'title': _('Readonly fields'),
            'classes': ('collapse',),
            'fields': ('active', 'date_create', 'date_update',),
        },
    }

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj=None, **kwargs)
        form.base_fields['page'].label_from_instance = lambda obj: (
            '%s %s' % ('.. ' * (obj.depth - 1), obj)
        )
        return form
