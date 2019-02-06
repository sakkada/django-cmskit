from django.contrib.sites.shortcuts import get_current_site
from nodes.base import Menu, NavigationNode


class PageMenu(Menu):
    model_class = None
    navigation_node_class = NavigationNode

    def get_data(self, node):
        attr = {
            'reverse_id': '%s_%s' % (node.__class__.__name__.lower(), node.pk),
            'auth_required': node.menu_login_required,
            'show_meta_selected': node.menu_show_current,
            'jump': node.menu_jump,
            'title': node.title,
            #'meta_title': node.meta_title,
            #'meta_keywords': node.meta_keywords,
            #'meta_description': node.meta_description,
            'visible_in_chain': node.menu_in_chain,
        }

        if node.menu_extender:
            attr['navigation_extenders'] = [
                i.strip() for i in node.menu_extender.split(',') if i.strip()
            ]
        return attr

    def get_queryset(self, request):
        return self.model_class.objects.active().specific()

    def get_nodes(self, request):
        if not self.model_class:
            raise Exception('model_class variable not defined in NodeMenu')
        pages = self.get_queryset(request)
        nodes, home, cut_branch, cut_level = [], None, False, None
        for page in pages:
            # remove inactive nodes
            if cut_branch:
                if cut_level < page.level: continue
                cut_branch = False
            if not self.node_is_active(page):
                cut_branch = True
                cut_level = page.level
                continue
            nodes.append(self.node_to_navinode(page))
        return nodes

    def node_is_active(self, node):
        return node.active

    def node_to_navinode(self, node):
        n = self.navigation_node_class(
            node.get_menu_title(),
            node.get_absolute_url(),
            node.pk,
            node.parent_id,
            visible=node.menu_in,
            data=self.get_data(node),
        )
        return n
