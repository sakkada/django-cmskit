from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.shortcuts import get_object_or_404
from django.db.models import Q
from cmskit.base import registry
from cmskit.views import PageView
from cmskit.contrib.items.views import ItemPageView
from .models import Page, MTIPage, ItemPage, Item


class NodeView(PageView):
    # extra views
    # -----------
    def extraview_item_feedback(self, request, **kwargs):
        form = FeedbackForm(request.POST or None)
        if form.is_valid():
            form.sendmail()
            return HttpResponseRedirect('?success=yes')

        self.extra_context.update(form=form)


class MTIPageNodeVIew(NodeView):
    def consume_url_segments(self, page, segments):
        return segments[-1] == page.alt_title

    def behaviour(self):
        return super().behaviour()


"""
registry.register_view(Page, NodeView)
registry.register_view(MTIPage, MTIPageNodeVIew)
registry.register_view(PageItems, PageItemsView, item_model=Item)

registry.clear_templates()
registry.register_template({
    'name': 'base',
    'path': 'base.html',
    'title': _('General site template'),
    'areas': (
        ('header', _('Page header')),
        ('sidebar', _('Sidebar'),),
    ),
})
"""

registry.register_view(Page, PageView)
registry.register_view(MTIPage, MTIPageNodeVIew)
registry.register_view(ItemPage, ItemPageView)

main_view = NodeView.as_view(page_model=Page)
