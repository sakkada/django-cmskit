from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.core.paginator import Paginator, InvalidPage, EmptyPage
from django.views.generic import TemplateView
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.utils.decorators import classonlymethod
from .utils import jump_node_by_node
from .base import registry


class PageView(TemplateView):
    node = None
    extra_context = {}
    template_name_prefix = 'nodes'
    page_model = None

    @classonlymethod
    def as_view(cls, **initkwargs):
        if 'page_model' not in initkwargs and not self.page_model:
            raise TypeError('CMSKit view "%s" should receive "page_model" '
                            'kwarg in "as_view" method.' % cls.__name__)
        return super().as_view(**initkwargs)

    views_cache = None

    def get_view_for_page(self, page):
        view_func = registry.views.get(type(page), None)

        if not view_func:
            return self
        if self.views_cache is None:
            self.views_cache = {}
        view = self.views_cache.get(page.id, None)
        if not view:
            view = view_func.view_class(**view_func.view_initkwargs)
            if hasattr(view, 'get') and not hasattr(view, 'head'):
                view.head = view.get
            view.request = self.request
            view.args = self.args
            view.kwargs = self.kwargs
            self.views_cache[page.id] = view
        return view

    # allow post method for request
    def post(self, request, **kwargs):
        return self.get(request, **kwargs)

    def consume_url_segments(self, page, segments):
        return False

    # pretty-urls-fix
    def get(self, request, **kwargs):
        """get node data and call required view (node, list or item) or 404"""

        Page = self.page_model

        # get current node
        node = self.get_node(Page)

        # set instance data
        view = self.get_view_for_page(node)
        view.node = node

        context = view.behaviour()
        if issubclass(context.__class__, HttpResponse):
            return context

        context = view.get_context_data(**context)
        return view.render_to_response(context)

    def get_node_queryset(self, model):
        return model.objects.filter(active=True)

    def get_node(self, model):
        # 0. Get all appropriate nodes, each node will be loaded as specific
        # 2. Consume tail, if it exists, if result is not True, continue search
        # 3. If no one in the end, raise 404.

        """get curent node"""
        link = self.kwargs['path'].strip('/')
        path = link.split('/')

        # get all possible nodes (by path+slug or by link value)
        filter = Q()
        for i in range(len(path), 0, -1):
            filter |= Q(url_path='/'.join(path[:i]))

        # get node with deepest level or 404
        nodes = self.get_node_queryset(model).filter(filter).order_by(
            '-url_path', '-menu_weight',).specific()

        node = None
        for elem in nodes:
            if elem.url_path != link:
                # todo: require consume all tail
                segments = link[len(elem.url_path):].strip('/').split('/')
                view = self.get_view_for_page(elem)
                if not view.consume_url_segments(elem, segments):
                    continue
            node = elem
            break

        if not node:
            raise Http404('No any suitable page.')

        return node

    def behaviour(self):
        """main behaviour"""
        node = self.node

        # extra view
        if node.alt_view:
            response = self.get_alt_view_by_name(node.alt_view, 'node')
            if response:
                return response

        # menu jump
        node_to = node.menu_jump and jump_node_by_node(node)
        if node_to:
            return HttpResponseRedirect(node_to.get_absolute_url())

        return self.view_node()

    def view_node(self):
        """node self view"""
        self.set_template_name_variants('node', self.node.alt_template, [
            type(self.node), self.node.get_base_model()
        ])

        return {'node': self.node,}

    def get_template_names(self):
        if not self.template_name or not isinstance(self.template_name, list):
            raise Exception(
                'Node requires a definition of template_name as list'
                ' or an implementation of get_template_names()')
        return self.template_name

    def get_context_data(self, **kwargs):
        context = kwargs
        context.update(self.extra_context)
        return context

    def set_template_name_variants(self, template_type,
                                   template_name=None, models=None,):
        bases = ['%s.html' % template_type]
        if template_name:
            bases = ['%s.%s.html' % (template_type, template_name)] + bases
        paths = ['%s/%%s' % self.template_name_prefix]
        if models:
            paths = [
                '%s/%s/%%s' % (self.template_name_prefix,
                               model._meta.model_name) for model in models
            ] + paths

        self.template_name = [(p % b) for b in bases for p in paths]

    def get_alt_view_by_name(self, view_name, obj_type):
        """get extraview by name and type"""
        view_ex = 'alt_view_%s_%s' % (obj_type, view_name)
        view_ex = getattr(self, view_ex, None)
        view_ex = view_ex if callable(view_ex) else None
        if not view_ex:
            raise Http404(
                u'Extra view "%s" for node "%s/%s(%s)" is not accessible.'
                % (self.node.view, self.node.node_name, self.node.slug,
                   self.node.pk))
        response = view_ex(self.request, **self.kwargs)
        return response if issubclass(response.__class__,
                                      HttpResponse) else None
