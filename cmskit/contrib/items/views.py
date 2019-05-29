from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.core.paginator import Paginator, InvalidPage, EmptyPage
from django.views.generic import TemplateView
from django.shortcuts import get_object_or_404
from django.db.models import Q
from cmskit.utils import jump_node_by_node
from cmskit.utils.pagination import Pagination
from cmskit.utils.querystring import QueryString
from cmskit.views import PageView


class ItemPageView(PageView):
    node = None
    queryset_list = None
    queryset_item = None
    extra_context = {}
    pagination = Pagination

    def consume_url_segments(self, page, segments):
        if not len(segments) == 1:
            return False
        if page.items.filter(slug=segments[0]).exists():
            self.kwargs['item'] = segments[0]
            return True
        return False

    def show_in_meta_handler(self, item):
        # self.request.meta.chain.append(
        #     {'link':self.request.get_full_path(), 'name':item.name})
        # self.request.meta.title.append(item.meta_title or item.name)
        # self.request.meta.keywords.append(item.meta_keywords)
        # self.request.meta.description.append(item.meta_description)
        pass

    def prepare_querysets(self):
        node = self.node
        item = self.kwargs.get('item', None)

        self.queryset_list = node.get_item_queryset().visible()
        self.queryset_item = (
            node.get_item_queryset().filter(slug=item) if item else None)

    def behaviour(self):
        node = self.node

        self.prepare_querysets()

        # extra view
        if node.alt_view:
            response = self.get_alt_view_by_name(node.alt_view, 'node')
            if response:
                return response

        # menu jump
        node_to = node.menu_jump and jump_node_by_node(node)
        if node_to:
            return HttpResponseRedirect(node_to.get_absolute_url())

        # main item behaviour
        if node.behaviour == 'node':
            return self.view_node()
        elif node.behaviour == 'item' or 'item' in self.kwargs:
            return self.view_item()
        else:
            return self.view_list()

    def view_list(self):
        """node list of items view"""
        node    = self.node
        onpage  = node.onpage if 0 < node.onpage < 1000 else 10

        # paginator and page
        paginator   = Paginator(self.queryset_list, onpage)
        page        = self.request.GET.get('page', '1')
        page        = int(page) if page.isdigit() else 1
        try:
            page_item = paginator.page(page)
        except (EmptyPage, InvalidPage):
            page      = paginator.num_pages
            page_item = paginator.page(page)
        page_item.pagination = self.pagination(page_item)
        # end paginator

        self.set_template_name_variants('list', node.alt_template, [
            type(node), node.get_base_model(),
        ])

        context = {
            'node': node,
            'page_item': page_item,
            'url_no_page': node.get_absolute_url(),
            'querystring': QueryString(self.request),
        }

        return context

    def view_item(self):
        """node item's detail view"""
        queryset = (self.queryset_list if self.queryset_item is None else
                    self.queryset_item)

        # get item or 404
        item = get_object_or_404(queryset[:1])

        # extended view
        if item.alt_view:
            response = self.get_alt_view_by_name(item.alt_view, 'item')
            if response:
                return response

        # storage meta data
        if item.show_in_meta:
            self.show_in_meta_handler(item)

        self.set_template_name_variants(
            'item', item.alt_template or item.page.alt_template,
            [type(self.node), self.node.get_base_model(),])

        context = {
            'item': item,
            'node': self.node,
            'querystring': QueryString(self.request),
        }

        return context
