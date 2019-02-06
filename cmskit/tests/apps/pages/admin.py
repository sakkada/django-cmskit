from django.contrib import admin
from treebeard.admin import TreeAdmin
from cmskit.admin import PageBaseAdmin
from cmskit.contrib.items.admin import ItemAdmin
from . import models


class PageAdmin(PageBaseAdmin, TreeAdmin):
    search_fields = ('title',)
    list_display = ('title', 'id', 'content_type', 'depth', 'path', 'numchild', 'published', 'active', 'slug',
        #'slug_path',
        'url_path',
        #'url_name',
        #'url_text',
    )
    list_editable = ('published',)


class MTIPageAdmin(admin.ModelAdmin):
    list_display = ('title', 'id',)


class STIPageAdmin(TreeAdmin):
    list_display = ('title', 'id',)


admin.site.register(models.Page, PageAdmin)
#admin.site.register(models.MTIPage, MTIPageAdmin)
#admin.site.register(models.MMTIPage)
#admin.site.register(models.STIPage, STIPageAdmin)
#admin.site.register(models.SSTIPage)
admin.site.register(models.PageItems)
admin.site.register(models.Item, ItemAdmin)
