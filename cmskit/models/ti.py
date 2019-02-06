import logging
import posixpath
from collections import defaultdict

from django.db import models
from django.db.models import CharField, Q
from django.db.models.functions import Length, Substr
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.utils.functional import cached_property


logger = logging.getLogger('cmskit.models')

TI_MODEL_CLASSES = {}


# Model Meta Class section
# ------------------------
class TIModelBase(models.base.ModelBase):
    """Metaclass for TI Models"""
    def __init__(cls, name, bases, dct):
        super().__init__(name, bases, dct)

        # Register this type in the list of TI content types.
        if not cls._meta.abstract:
            TI_MODEL_CLASSES.setdefault(cls.get_base_model(), []).append(cls)


# Model Class section
# -------------------
class TIBaseModel(models.Model):

    class Meta:
        abstract = True

    @classmethod
    def get_base_model(cls):
        """Return deepest non proxy model."""
        root = cls
        while root._meta.parents:
            root = list(root._meta.parents)[0]
        return root

    @classmethod
    def get_page_models(cls, model=None):
        """
        Returns a list of all non-abstract Page model classes
        defined for particular model.
        """
        return TI_MODEL_CLASSES.get((model or cls).get_base_model(), [])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.id:
            # this model is being newly created
            # rather than retrieved from the db;
            if not self.content_type_id:
                # set content type to correctly represent the model class
                # that this was created as
                self.content_type = ContentType.objects.get_for_model(self)

    #: Return this page in its most specific subclassed form.
    @cached_property
    def specific(self):
        """
        Return this page in its most specific subclassed form.
        """
        # the ContentType.objects manager keeps a cache, so this should potentially
        # avoid a database lookup over doing self.content_type. I think.
        content_type = ContentType.objects.get_for_id(self.content_type_id)
        model_class = content_type.model_class()
        if model_class is None:
            # Cannot locate a model class for this content type. This might happen
            # if the codebase and database are out of sync (e.g. the model exists
            # on a different git branch and we haven't rolled back migrations before
            # switching branches); if so, the best we can do is return the page
            # unchanged.
            return self
        elif isinstance(self, model_class):
            # self is already the an instance of the most specific class
            return self
        else:
            return content_type.get_object_for_this_type(id=self.id)

    #: Return the class that this page would be if instantiated in its
    #: most specific form
    @cached_property
    def specific_class(self):
        """
        Return the class that this page would be if instantiated in its
        most specific form
        """
        content_type = ContentType.objects.get_for_id(self.content_type_id)
        return content_type.model_class()


# QuerySet section
# ----------------
class TIQuerySet(models.query.QuerySet):
    def type_q(self, klass):
        content_types = ContentType.objects.get_for_models(*[
            model for model in apps.get_models()
            if issubclass(model, klass)
        ]).values()

        return Q(content_type__in=content_types)

    def type(self, model):
        """
        This filters the QuerySet to only contain pages that are an instance
        of the specified model (including subclasses).
        """
        return self.filter(self.type_q(model))

    def not_type(self, model):
        """
        This filters the QuerySet to not contain any pages which are
        an instance of the specified model.
        """
        return self.exclude(self.type_q(model))

    def exact_type_q(self, klass):
        return Q(content_type=ContentType.objects.get_for_model(klass))

    def exact_type(self, model):
        """
        This filters the QuerySet to only contain pages that are
        an instance of the specified model
        (matching the model exactly, not subclasses).
        """
        return self.filter(self.exact_type_q(model))

    def not_exact_type(self, model):
        """
        This filters the QuerySet to not contain any pages which are
        an instance of the specified model
        (matching the model exactly, not subclasses).
        """
        return self.exclude(self.exact_type_q(model))

    def first_common_ancestor(self, include_self=False, strict=False):
        """
        Find the first ancestor that all pages in this queryset have in common.
        For example, consider a page hierarchy like::

            - Home/
                - Foo Event Index/
                    - Foo Event Page 1/
                    - Foo Event Page 2/
                - Bar Event Index/
                    - Bar Event Page 1/
                    - Bar Event Page 2/

        The common ancestors for some queries would be:

        .. code-block:: python

            >>> Page.objects\\
            ...     .type(EventPage)\\
            ...     .first_common_ancestor()
            <Page: Home>
            >>> Page.objects\\
            ...     .type(EventPage)\\
            ...     .filter(title__contains='Foo')\\
            ...     .first_common_ancestor()
            <Page: Foo Event Index>

        This method tries to be efficient, but if you have millions of pages
        scattered across your page tree, it will be slow.

        If `include_self` is True, the ancestor can be one of the pages in the
        queryset:

        .. code-block:: python

            >>> Page.objects\\
            ...     .filter(title__contains='Foo')\\
            ...     .first_common_ancestor()
            <Page: Foo Event Index>
            >>> Page.objects\\
            ...     .filter(title__exact='Bar Event Index')\\
            ...     .first_common_ancestor()
            <Page: Bar Event Index>

        A few invalid cases exist: when the queryset is empty, when the root
        Page is in the queryset and ``include_self`` is False, and when there
        are multiple page trees with no common root (a case Wagtail does not
        support). If ``strict`` is False (the default), then the first root
        node is returned in these cases. If ``strict`` is True, then a
        ``ObjectDoesNotExist`` is raised.
        """
        # An empty queryset has no ancestors. This is a problem
        if not self.exists():
            if strict:
                raise self.model.DoesNotExist(
                    'Can not find ancestor of empty queryset')
            return self.model.get_first_root_node()

        if include_self:
            # Get all the paths of the matched pages.
            paths = self.order_by().values_list('path', flat=True)
        else:
            # Find all the distinct parent paths of all matched pages.
            # The empty `.order_by()` ensures that `Page.path` is not also
            # selected to order the results, which makes `.distinct()` works.
            paths = self.order_by()\
                .annotate(parent_path=Substr(
                    'path', 1, Length('path') - self.model.steplen,
                    output_field=CharField(max_length=255)))\
                .values_list('parent_path', flat=True)\
                .distinct()

        # This method works on anything, not just file system paths.
        common_parent_path = posixpath.commonprefix(paths)

        # That may have returned a path like (0001, 0002, 000), which is
        # missing some chars off the end. Fix this by trimming the path to a
        # multiple of `Page.steplen`
        extra_chars = len(common_parent_path) % self.model.steplen
        if extra_chars != 0:
            common_parent_path = common_parent_path[:-extra_chars]

        if common_parent_path is '':
            # This should only happen when there are multiple trees,
            # a situation that Wagtail does not support;
            # or when the root node itself is part of the queryset.
            if strict:
                raise self.model.DoesNotExist('No common ancestor found!')

            # Assuming the situation is the latter, just return the root node.
            # The root node is not its own ancestor, so this is technically
            # incorrect. If you want very correct operation, use `strict=True`
            # and receive an error.
            return self.model.get_first_root_node()

        # Assuming the database is in a consistent state, this page should
        # *always* exist. If your database is not in a consistent state, you've
        # got bigger problems.
        return self.model.objects.get(path=common_parent_path)

    def specific(self, defer=False):
        """
        This efficiently gets all the specific pages for the queryset, using
        the minimum number of queries.

        When the "defer" keyword argument is set to True, only the basic page
        fields will be loaded and all specific fields will be deferred. It
        will still generate a query for each page type though (this may be
        improved to generate only a single query in a future release).
        """
        clone = self._clone()
        if defer:
            clone._iterable_class = DeferredSpecificIterable
        else:
            clone._iterable_class = SpecificIterable
        return clone


def specific_iterator(qs, defer=False):
    """
    This efficiently iterates all the specific pages in a queryset, using
    the minimum number of queries.

    This should be called from ``PageQuerySet.specific``
    """
    pks_and_types = qs.values_list('pk', 'content_type')
    pks_by_type = defaultdict(list)
    for pk, content_type in pks_and_types:
        pks_by_type[content_type].append(pk)

    # Content types are cached by ID, so this will not run any queries.
    content_types = {pk: ContentType.objects.get_for_id(pk)
                     for _, pk in pks_and_types}

    # Get the specific instances of all pages, one model class at a time.
    pages_by_type = {}
    for content_type, pks in pks_by_type.items():
        # look up model class for this content type, falling back on the original
        # model (i.e. Page) if the more specific one is missing
        model = content_types[content_type].model_class() or qs.model
        pages = model.objects.filter(pk__in=pks)

        if defer:
            # Defer all specific fields
            from wagtail.core.models import Page
            fields = [field.attname for field in Page._meta.get_fields() if field.concrete]
            pages = pages.only(*fields)

        pages_by_type[content_type] = {page.pk: page for page in pages}

    # Yield all of the pages, in the order they occurred in the original query.
    for pk, content_type in pks_and_types:
        yield pages_by_type[content_type][pk]


class SpecificIterable(models.query.BaseIterable):
    def __iter__(self):
        return specific_iterator(self.queryset)


class DeferredSpecificIterable(models.query.BaseIterable):
    def __iter__(self):
        return specific_iterator(self.queryset, defer=True)
