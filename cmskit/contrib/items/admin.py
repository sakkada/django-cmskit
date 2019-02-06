from django.utils.translation import ugettext_lazy as _
from django.urls import reverse
from django.contrib import admin
from django.db import models
from django import forms


class NodeAdmin(admin.ModelAdmin):
    list_display = ('title', 'id', 'slug', 'level',)
    list_display_links = ('id',)
    list_filter = ('level',)

    ordering = ('site', 'tree_id', 'lft',)
    prepopulated_fields = {'slug': ('title',)}
    wideinput_fields = ('title', 'slug', 'link', 'menu_title', 'menu_extender',
                        'meta_title', 'meta_keywords', 'template', 'view', 'order_by',)
    fieldsets = (
        (None, {
            'fields': ('title', 'active', 'text')
        }),
        (_('path and relation settings'), {
            'classes': ('collapse',),
            'fields': ('slug', 'link', 'parent', 'site',)
        }),
        (_('menu settings'), {
            'classes': ('collapse',),
            'fields': ('menu_title', 'menu_extender', 'menu_in', 'menu_in_chain',
                       'menu_jump', 'menu_login_required', 'menu_show_current')
        }),
        (_('meta settings'), {
            'classes': ('collapse',),
            'fields': ('meta_title', 'meta_keywords', 'meta_description',)
        }),
        (_('behaviour settings'), {
            'classes': ('collapse',),
            'fields': ('behaviour', 'filter', 'filter_date', 'template',
                       'view', 'order_by', 'onpage')
        }),
    )


class ItemAdmin(admin.ModelAdmin):
    list_display = ('title', 'id', 'slug', 'weight', 'page', 'active', 'published',)
    list_filter = ('page', 'date_create',)

    ordering = ('-weight',)
    search_fields = ('title',)
    prepopulated_fields = {'slug': ('title',)}
    #wideinput_fields = ('title', 'slug', 'link', 'meta_title', 'meta_keywords',
    #                    'template', 'view',)
    readonly_fields = ('active', 'date_create', 'date_update',)
    fieldsets = (
            (None, {
                'fields': (('date_start', 'date_end',), 'title',
                           ('weight', 'published',), 'brief', 'text',),
            }),
            (_('readonly fields'), {
                'classes': ('collapse',),
                'fields': ('active', 'date_create', 'date_update',),
            }),
            (_('path and node settings'), {
                'classes': ('collapse',),
                'fields': ('slug', 'url', 'page',),
            }),
            #(_('meta settings'), {
            #    'classes': ('collapse',),
            #    'fields': ('meta_title', 'meta_keywords', 'meta_description',),
            #}),
            (_('behaviour settings'), {
                'classes': ('collapse',),
                'fields': ('alt_template', 'alt_view', 'visible', 'show_item_name',
                           'show_node_link', 'show_in_meta',),
            }),
        )

    def formfield_for_dbfield(self, db_field, **kwargs):
        field = super(ItemAdmin, self).formfield_for_dbfield(db_field, **kwargs)
        # set size=100 for each wideinput_fields and remove vTextField class
        if hasattr(self, 'wideinput_fields') and db_field.name in self.wideinput_fields:
            attrs = field.widget.attrs
            attrs.update(size=85)
            if 'vTextField' in attrs.get('class', ''):
                attrs['class'] = attrs['class'].replace('vTextField', '').strip()
        return field

    def get_form(self, request, obj=None, **kwargs):
        form = super(ItemAdmin, self).get_form(request, obj=None, **kwargs)
        # indent tree node titles
        form.base_fields['page'].label_from_instance = lambda obj: u'%s %s' % \
                                                                   ('. ' * (obj.depth-1), obj)
        return form
