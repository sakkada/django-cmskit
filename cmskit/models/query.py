from django.db.models import Q, Manager
from treebeard.mp_tree import MP_NodeQuerySet
from .ti import TIQuerySet


class TreeQuerySet(MP_NodeQuerySet):
    """
    Extends Treebeard's MP_NodeQuerySet with additional useful tree-related operations.
    """
    def descendant_of_q(self, other, inclusive=False):
        q = Q(path__startswith=other.path) & Q(depth__gte=other.depth)

        if not inclusive:
            q &= ~Q(pk=other.pk)

        return q

    def descendant_of(self, other, inclusive=False):
        """
        This filters the QuerySet to only contain pages that descend from the specified page.

        If inclusive is set to True, it will also contain the page itself (instead of just its descendants).
        """
        return self.filter(self.descendant_of_q(other, inclusive))

    def not_descendant_of(self, other, inclusive=False):
        """
        This filters the QuerySet to not contain any pages that descend from the specified page.

        If inclusive is set to True, it will also exclude the specified page.
        """
        return self.exclude(self.descendant_of_q(other, inclusive))

    def child_of_q(self, other):
        return self.descendant_of_q(other) & Q(depth=other.depth + 1)

    def child_of(self, other):
        """
        This filters the QuerySet to only contain pages that are direct children of the specified page.
        """
        return self.filter(self.child_of_q(other))

    def not_child_of(self, other):
        """
        This filters the QuerySet to not contain any pages that are direct children of the specified page.
        """
        return self.exclude(self.child_of_q(other))

    def ancestor_of_q(self, other, inclusive=False):
        paths = [
            other.path[0:pos]
            for pos in range(0, len(other.path) + 1, other.steplen)[1:]
        ]
        q = Q(path__in=paths)

        if not inclusive:
            q &= ~Q(pk=other.pk)

        return q

    def ancestor_of(self, other, inclusive=False):
        """
        This filters the QuerySet to only contain pages that are ancestors of the specified page.

        If inclusive is set to True, it will also include the specified page.
        """
        return self.filter(self.ancestor_of_q(other, inclusive))

    def not_ancestor_of(self, other, inclusive=False):
        """
        This filters the QuerySet to not contain any pages that are ancestors of the specified page.

        If inclusive is set to True, it will also exclude the specified page.
        """
        return self.exclude(self.ancestor_of_q(other, inclusive))

    def parent_of_q(self, other):
        return Q(path=self.model._get_parent_path_from_path(other.path))

    def parent_of(self, other):
        """
        This filters the QuerySet to only contain the parent of the specified page.
        """
        return self.filter(self.parent_of_q(other))

    def not_parent_of(self, other):
        """
        This filters the QuerySet to exclude the parent of the specified page.
        """
        return self.exclude(self.parent_of_q(other))

    def sibling_of_q(self, other, inclusive=True):
        q = Q(path__startswith=self.model._get_parent_path_from_path(other.path)) & Q(depth=other.depth)

        if not inclusive:
            q &= ~Q(pk=other.pk)

        return q

    def sibling_of(self, other, inclusive=True):
        """
        This filters the QuerySet to only contain pages that are siblings of the specified page.

        By default, inclusive is set to True so it will include the specified page in the results.

        If inclusive is set to False, the page will be excluded from the results.
        """
        return self.filter(self.sibling_of_q(other, inclusive))

    def not_sibling_of(self, other, inclusive=True):
        """
        This filters the QuerySet to not contain any pages that are siblings of the specified page.

        By default, inclusive is set to True so it will exclude the specified page from the results.

        If inclusive is set to False, the page will be included in the results.
        """
        return self.exclude(self.sibling_of_q(other, inclusive))


class PageQuerySet(TIQuerySet, TreeQuerySet):
    def unpublish(self):
        """
        This unpublishes all live pages in the QuerySet.
        """
        for page in self.live():
            page.unpublish()

    def active(self):
        return self.filter(active=True)


class BasePageManager(Manager):
    def get_queryset(self):
        return self._queryset_class(self.model).order_by('path')

    def active(self):
        return self.get_queryset().active()


PageManager = BasePageManager.from_queryset(PageQuerySet)
