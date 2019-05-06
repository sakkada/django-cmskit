from django.contrib.sites.shortcuts import get_current_site
from nodes.base import Menu, registry


class PageMenu(Menu):
    model_class = None
    navigation_node_class = registry.navigation_node

    def get_data(self, page):
        attr = {
            'reverse_id': '%s_%s' % (page.__class__.__name__.lower(), page.pk),
            'auth_required': page.menu_login_required,
            'show_meta_selected': page.menu_show_current,
            'jump': page.menu_jump,
            'title': page.title,
            'visible_in_chain': page.menu_in_chain,
        }
        if page.menu_extender:
            attr['navigation_extenders'] = [
                i.strip() for i in page.menu_extender.split(',') if i.strip()
            ]
        # builtin metatags support (see contrib.metatags app)
        if hasattr(page, 'get_metatags'):
            attr['metatags'] = page.get_metatags()
        return attr

    def get_queryset(self, request):
        return self.model_class.objects.active().specific()

    def get_nodes(self, request):
        if not self.model_class:
            raise ValueError('model_class variable is not defined in PageMenu')
        pages = self.get_queryset(request)
        nodes, home, cut_branch, cut_level = [], None, False, None
        for page in pages:
            # remove inactive nodes
            if cut_branch:
                if cut_level < page.level: continue
                cut_branch = False
            if not self.page_is_active(page):
                cut_branch = True
                cut_level = page.level
                continue
            nodes.append(self.page_to_navigation_node(page))
        return nodes

    def page_is_active(self, page):
        return page.active

    def page_to_navigation_node(self, page):
        n = self.get_navigation_node_class()(
            page.get_menu_title(),
            page.get_absolute_url(),
            page.pk,
            page.parent_id,
            visible=page.menu_in,
            data=self.get_data(page),
        )
        return n
