import json
import logging
from io import StringIO
from urllib.parse import urlparse
from collections import defaultdict

from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core import checks
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.handlers.base import BaseHandler
from django.core.handlers.wsgi import WSGIRequest
from django.db import models, transaction
from django.db.models import Q, Value
from django.db.models.functions import Concat, Substr
from django.http import Http404
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.text import capfirst, slugify
from django.utils.translation import ugettext_lazy as _
from treebeard.mp_tree import MP_Node
from treebeard.exceptions import InvalidPosition

from .query import PageManager
from .ti import TIModelBase, TIBaseModel
from ..utils import resolve_model_string


logger = logging.getLogger('cmskit.models')


class PageBase(TIModelBase):
    """Metaclass for Page"""
    def __init__(cls, name, bases, dct):
        super().__init__(name, bases, dct)

        cls._clean_subpage_models = None
        # to be filled in on first call to cls.clean_subpage_models
        cls._clean_parent_page_models = None
        # to be filled in on first call to cls.clean_parent_page_models

        # All pages should be creatable unless explicitly set otherwise.
        # This attribute is not inheritable.
        if 'is_creatable' not in dct:
            cls.is_creatable = not cls._meta.abstract


class BasePage(TIBaseModel, MP_Node, metaclass=PageBase):
    """
    Abstract superclass for Page. According to Django's inheritance rules,
    managers set on abstract models are inherited by subclasses, but managers
    set on concrete models that are extended via multi-table inheritance
    are not. We therefore need to attach PageManager to an abstract superclass
    to ensure that it is retained by subclasses of Page.
    """

    BEHAVIOUR_CHOICES = (
        ('node', _('always node')),
    )
    ALT_TEMPLATE_CHOICES = ()
    URL_NAME_IGNORED = (
        r'^admin\:', r'^django-admindocs-',
    )

    content_type = models.ForeignKey(
        'contenttypes.ContentType', null=True, editable=False,
        on_delete=models.SET_NULL, verbose_name=_('content type'))
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, verbose_name=_('owner'))
    parent = models.ForeignKey('self', null=True, blank=True, editable=False,
        related_name='children', on_delete=models.SET_NULL,
        verbose_name=_('parent page'))

    title = models.CharField(_('title'), max_length=2048)

    active = models.BooleanField(_('is active'), default=False, editable=False)
    published = models.BooleanField(_('is published'), default=False)

    # path
    slug = models.SlugField(_('slug'), max_length=255)
    slug_path = models.CharField(
        _('slug path'), max_length=1024, editable=False)

    url_path = models.CharField(
        _('url path'), max_length=1024, null=True, db_index=True,
        editable=False, default=None,
        help_text='Automatically generated, empty value means inaccessibility.')
    url_name = models.CharField(_('url name'), max_length=1024, blank=True)
    url_text = models.CharField(
        _('url text'), max_length=1024, blank=True, help_text=_(
            'Overwrite the path to this node (if leading slashes '
            '("/some/url/") - node is only link in menu, else '
            '("some/url") - standart behaviour).'
        ))

    base_template = models.CharField(
        _('base template'), max_length=128, blank=True, default='',
        help_text=_('The extendable base template name.'))

    # behaviour
    behaviour = models.CharField(_('behaviour'), max_length=32, blank=True)

    alt_template = models.CharField(
        _('alternative template'), max_length=128, blank=True,
        help_text=_('The template used to render the content instead original.'))
    alt_view = models.CharField(
        _('alternative view'), max_length=128, blank=True,
        help_text=_('The view loaded instead original.'))

    # menu
    menu_weight = models.IntegerField(_('menu weight'), default=500)
    menu_title = models.CharField(
        _('menu title'), max_length=255, blank=True,
        help_text=_('Overwrite the title in the menu.'))
    menu_extender = models.CharField(
        _('attached menu'), max_length=64, db_index=True, blank=True,
        help_text=_('Menu extender class name.'))
    menu_in = models.BooleanField(
        _('in navigation'), default=True, db_index=True,
        help_text=_('This node in navigation (menu in?).'))
    menu_in_chain = models.BooleanField(
        _('in chain and title'), default=True, db_index=True,
        help_text=_('This node in chain and title (chain in?).'))
    menu_jump = models.BooleanField(
        _('jump to first child'), default=False,
        help_text=_('Jump to the first child element if exist (jump?).'))
    menu_login_required = models.BooleanField(
        _('menu login required'), default=False,
        help_text=_('Show in menu only if user is logged in (login?).'))
    menu_show_current = models.BooleanField(
        _('show node name'), default=True,
        help_text=_('Show node name in h1 tag if current (h1 title?).'))

    # stat info
    date_create = models.DateTimeField(editable=False, auto_now_add=True)
    date_update = models.DateTimeField(editable=False, auto_now=True)

    objects = PageManager()

    # Do not allow plain Page instances to be created through the admin
    is_creatable = False

    # Define the maximum number of instances this page type can have. Default to unlimited.
    max_count = None

    view_name = '{app_label}:{app_label}_{model_name}_details'

    class Meta:
        verbose_name = _('Page')
        verbose_name_plural = _('Pages')
        abstract = True

    def get_menu_title(self):
        return self.menu_title or self.title

    @classmethod
    def check(cls, **kwargs):
        errors = super(BasePage, cls).check(**kwargs)

        # Check that foreign keys from pages are not configured to cascade
        # This is the default Django behaviour which must be explicitly overridden
        # to prevent pages disappearing unexpectedly and the tree being corrupted

        # get names of foreign keys pointing to parent classes (such as page_ptr)
        field_exceptions = [field.name
                            for model in [cls] + list(cls._meta.get_parent_list())
                            for field in model._meta.parents.values() if field]

        # todo: add view existing checking
        for field in cls._meta.fields:
            if isinstance(field, models.ForeignKey) and field.name not in field_exceptions:
                if field.remote_field.on_delete == models.CASCADE:
                    errors.append(
                        checks.Warning(
                            "Field hasn't specified on_delete action",
                            hint="Set on_delete=models.SET_NULL and make sure the field is nullable or set on_delete=models.PROTECT. Wagtail does not allow simple database CASCADE because it will corrupt its tree storage.",
                            obj=field,
                            id='wagtailcore.W001',
                        )
                    )

        if not isinstance(cls.objects, PageManager):
            errors.append(
                checks.Error(
                    "Manager does not inherit from PageManager",
                    hint=("Ensure that custom Page managers inherit from"
                          " cmskit.models.PageManager"),
                    obj=cls,
                    id='cmskit.E001',
                )
            )

        try:
            cls.clean_subpage_models()
        except (ValueError, LookupError) as e:
            errors.append(
                checks.Error(
                    "Invalid subpage_types setting for %s" % cls,
                    hint=str(e),
                    id='cmskit.E002'
                )
            )

        try:
            cls.clean_parent_page_models()
        except (ValueError, LookupError) as e:
            errors.append(
                checks.Error(
                    "Invalid parent_page_types setting for %s" % cls,
                    hint=str(e),
                    id='cmskit.E003'
                )
            )

        return errors

    def __str__(self):
        return self.title

    def unpublish(self, set_expired=False, commit=True):
        if self.live:
            logger.info("Page unpublished: \"%s\" id=%d", self.title, self.id)

    def get_template(self, request, *args, **kwargs):
        if request.is_ajax():
            return self.ajax_template or self.template
        else:
            return self.template

    @classmethod
    def clean_subpage_models(cls):
        """
        Returns the list of subpage types, normalised as model classes.
        Throws ValueError if any entry in subpage_types cannot be recognised as a model name,
        or LookupError if a model does not exist (or is not a Page subclass).
        """
        if cls._clean_subpage_models is None:
            subpage_types = getattr(cls, 'subpage_types', None)
            if subpage_types is None:
                # if subpage_types is not specified on the Page class, allow all page types as subpages
                cls._clean_subpage_models = cls.get_page_models()
            else:
                cls._clean_subpage_models = [
                    resolve_model_string(model_string, cls._meta.app_label)
                    for model_string in subpage_types
                ]

                for model in cls._clean_subpage_models:
                    if not issubclass(model, BasePage):
                        raise LookupError("%s is not a Page subclass" % model)

        return cls._clean_subpage_models

    @classmethod
    def clean_parent_page_models(cls):
        """
        Returns the list of parent page types, normalised as model classes.
        Throws ValueError if any entry in parent_page_types cannot be recognised as a model name,
        or LookupError if a model does not exist (or is not a Page subclass).
        """

        if cls._clean_parent_page_models is None:
            parent_page_types = getattr(cls, 'parent_page_types', None)
            if parent_page_types is None:
                # if parent_page_types is not specified on the Page class, allow all page types as subpages
                cls._clean_parent_page_models = cls.get_page_models()
            else:
                cls._clean_parent_page_models = [
                    resolve_model_string(model_string, cls._meta.app_label)
                    for model_string in parent_page_types
                ]

                for model in cls._clean_parent_page_models:
                    if not issubclass(model, BasePage):
                        raise LookupError("%s is not a Page subclass" % model)

        return cls._clean_parent_page_models

    @classmethod
    def allowed_parent_page_models(cls):
        """
        Returns the list of page types that this page type can be a subpage of,
        as a list of model classes
        """
        return [
            parent_model for parent_model in cls.clean_parent_page_models()
            if cls in parent_model.clean_subpage_models()
        ]

    @classmethod
    def allowed_subpage_models(cls):
        """
        Returns the list of page types that this page type can have as subpages,
        as a list of model classes
        """
        return [
            subpage_model for subpage_model in cls.clean_subpage_models()
            if cls in subpage_model.clean_parent_page_models()
        ]

    @classmethod
    def creatable_subpage_models(cls):
        """
        Returns the list of page types that may be created under this page type,
        as a list of model classes
        """
        return [
            page_model for page_model in cls.allowed_subpage_models()
            if page_model.is_creatable
        ]

    @classmethod
    def can_exist_under(cls, parent):
        """
        Checks if this page type can exist as a subpage under a parent page
        instance.

        See also: :func:`Page.can_create_at` and :func:`Page.can_move_to`
        """
        return cls in parent.specific_class.allowed_subpage_models()

    @classmethod
    def can_create_at(cls, parent):
        """
        Checks if this page type can be created as a subpage under a parent
        page instance.
        """
        return cls.is_creatable and cls.can_exist_under(parent)

    def can_move_to(self, parent):
        """
        Checks if this page instance can be moved to be a subpage of a parent
        page instance.
        """
        return self.can_exist_under(parent)

    def get_ancestors(self, inclusive=False):
        return type(self).objects.ancestor_of(self, inclusive)

    def get_descendants(self, inclusive=False):
        return type(self).objects.descendant_of(self, inclusive)

    def get_siblings(self, inclusive=True):
        return type(self).objects.sibling_of(self, inclusive)

    def get_next_siblings(self, inclusive=False):
        return self.get_siblings(inclusive).filter(path__gte=self.path).order_by('path')

    def get_prev_siblings(self, inclusive=False):
        return self.get_siblings(inclusive).filter(path__lte=self.path).order_by('-path')

    @classmethod
    def get_verbose_name(cls):
        """
        Returns the human-readable "verbose name" of this page model e.g "Blog page".
        """
        # This is similar to doing cls._meta.verbose_name.title()
        # except this doesn't convert any characters to lowercase
        return capfirst(cls._meta.verbose_name)

    @property
    def status_string(self):
        if not self.active:
            if self.published:
                return _("unpublished")
            else:
                return _("published + inactive")
        else:
            return _("published + active")









    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.id and not self.content_type_id:
            # this model is being newly created
            # rather than retrieved from the db;
            # set content type to correctly represent the model class
            # that this was created as
            self.content_type = ContentType.objects.get_for_model(self)

    def get_path_or_url(self):
        path, url = None, None
        if self.url_name:
            url = reverse(self.url_name)
        elif self.url_text:
            if '://' in self.url_text or self.url_text.startswith('/'):
                url = self.url_text
            else:
                path = urlparse(self.url_text).path.strip('/')
        else:
            path = self.get_slug_path()
        return path, url

    @staticmethod
    def _slug_is_available(slug, parent_page, page=None):
        """
        Determine whether the given slug is available for use on a child page of
        parent_page. If 'page' is passed, the slug is intended for use on that page
        (and so it will be excluded from the duplicate check).
        """
        if parent_page is None:
            # the root page's slug can be whatever it likes...
            return True

        siblings = parent_page.get_children()
        if page:
            siblings = siblings.not_page(page)

        return not siblings.filter(slug=slug).exists()

    def _get_autogenerated_slug(self, base_slug):
        candidate_slug = base_slug
        suffix = 1
        parent_page = self.get_parent()

        while not Page._slug_is_available(candidate_slug, parent_page, self):
            # try with incrementing suffix until we find a slug which is available
            suffix += 1
            candidate_slug = "%s-%d" % (base_slug, suffix)

        return candidate_slug

    def full_clean(self, *args, **kwargs):
        # Apply fixups that need to happen before per-field validation occurs

        if not self.slug:
            # Try to auto-populate slug from title
            base_slug = slugify(self.title, allow_unicode=True)

            # only proceed if we get a non-empty base slug back from slugify
            if base_slug:
                self.slug = self._get_autogenerated_slug(base_slug)

        super().full_clean(*args, **kwargs)

    def clean(self):
        super().clean()
        #if not Page._slug_is_available(self.slug, self.get_parent(), self):
        #    raise ValidationError({'slug': _("This slug is already in use")})

    def get_slug_path(self):
        return (self.slug_path + '/' if self.slug_path else '') + self.slug

    def get_active(self):
        return self.published and (self.get_parent().active
                                   if self.get_parent() else True)

    def get_absolute_url(self):
        meta = self.get_base_model()._meta
        path, url = self.get_path_or_url()
        view_name = self.view_name.format(app_label=meta.app_label,
                                          model_name=meta.model_name)
        return reverse(view_name, kwargs={'path': path,}) if path else url

    # ensure that changes are only committed when we have updated all descendant URL paths, to preserve consistency
    @transaction.atomic
    def save(self, **kwargs):
        """Update path variable"""
        is_new, is_moved = self.pk is None, kwargs.pop('is_moved', False)
        parent = self.get_parent() and self.get_parent().specific

        # complex save if save run on non specific model
        if not is_new and not type(self) == type(self.specific):
            # save just data
            super().save(**kwargs)
            # run full featured save on specific model
            type(self.specific).objects.get(pk=self.pk).save(is_moved=True,
                                                             **kwargs)
            self.refresh_from_db()  # reload original instance
            return

        # check slug modification
        if not (is_new or is_moved):
            orig = type(self).objects.get(pk=self.pk)
            slug_path = parent.get_slug_path() if parent else ''
            is_moved = (orig.slug != self.slug or
                        orig.slug_path != slug_path or
                        orig.active != self.get_active())

        # get path value
        if is_new or is_moved:
            self.slug_path = parent.get_slug_path() if parent else ''
            self.active = self.get_active()
            self.parent = parent

        self.url_path = self.get_path_or_url()[0]

        super().save(**kwargs)

        # cascade children path updating
        if is_moved:
            self.page_is_moved_handler()
            for item in self.get_children():
                item.save(is_moved=True)

        # Log
        if is_new:
            logger.info(
                "Page created: \"%s\" id=%d content_type=%s.%s path=%s",
                self.title, self.id, type(self)._meta.app_label,
                type(self).__name__, self.url_path)

    def page_is_moved_handler(self):
        # Extend this method if some actions required after Page is moved.
        pass

    @transaction.atomic
    def move(self, target, pos=None):
        """
        Extension to the treebeard 'move' method to ensure that
        Page will be places to allowed position.
        """

        # todo: maybe move it to the special admin method
        cpos = ('first-child', 'last-child', 'sorted-child',)
        spos = ('first-sibling', 'left', 'right', 'last-sibling',
                'sorted-sibling',)
        page = self.specific
        if (pos in cpos and not page.can_move_to(target)) or (
                pos in spos and target.get_parent() and
                not page.can_move_to(target.get_parent())):
            raise InvalidPosition(
                'Can not move "%s" (%s) to %s (%s), '
                'allowed parent types are (%s).' % (
                    page, type(page).__name__,
                    target, target.specific_class.__name__,
                    ', '.join(i.__name__
                              for i in page.allowed_parent_page_models()),
                ))

        super().move(target, pos=pos)
        type(page).objects.get(id=page.id).save(is_moved=True)

        logger.info('Page moved: #%d "%s" to #%d: "%s" as "%s"',
                    page.id, page.title, target.id, target.title, pos)

    def delete(self, *args, **kwargs):
        # Ensure that deletion always happens on an instance of Page, not a specific subclass. This
        # works around a bug in treebeard <= 3.0 where calling SpecificPage.delete() fails to delete
        # child pages that are not instances of SpecificPage
        BasePage = self.get_base_model()
        if type(self) is BasePage:
            # this is a Page instance, so carry on as we were
            return super().delete(*args, **kwargs)
        else:
            # retrieve an actual Page instance and delete that instead of self
            return BasePage.objects.get(id=self.id).delete(*args, **kwargs)
