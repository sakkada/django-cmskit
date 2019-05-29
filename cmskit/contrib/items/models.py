import logging
from django.db import models
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _
from django.utils import timezone
from django.db import models, transaction
from cmskit.models import BasePage
from .query import ItemManager


logger = logging.getLogger('cmskit.models')


class BaseItemPage(models.Model):
    """A simple item list containing page model."""

    BEHAVIOUR_CHOICES = (
        ('item', _('always item')),
        ('node', _('always node')),
    )

    FILTER_CHOICES = (
        ('date_req', 'required date_start'),
    )
    FILTER_DATE_CHOICES = (
        ('date_actual', 'actual (date_start < date)'),
        ('date_actual_both', 'actual (date_start < date < date_end)'),
        ('date_anounce', 'anounce (date < date_start)'),
    )
    FILTER_FIELDS = ('filter', 'filter_date',)
    ORDER_BY_DEFAULT = ('-date_start', '-weight', '-id',)

    # behaviour
    filter = models.CharField(
        _('filter'), max_length=32, choices=FILTER_CHOICES, blank=True)
    filter_date = models.CharField(
        _('date filter'), max_length=32, choices=FILTER_DATE_CHOICES,
        blank=True)

    order_by = models.CharField(
        _('ordering'), max_length=128, blank=True, help_text=_(
            'Overwrite default ordering (default is empty, '
            'equal to "-date_start -weight", separate '
            'strongly with one space char)<br>possible keys: '
            'date_start, date_end, weight, title, slug, url.'
        ))
    onpage = models.PositiveSmallIntegerField(
        _('onpage'), default=10,
        help_text=_('Perpage count (default=10, 1<=count<=999).'))

    class Meta:
        verbose_name = _('Page with items')
        verbose_name_plural = _('Pages with items')
        abstract = True

    def get_order_by(self):
        fields = [i.name for i in self.items.model._meta.fields]
        order_by = [i for i in self.order_by.split(' ')
                    if i.replace('-', '', 1) in fields] if self.order_by else []
        order_by = order_by or self.ORDER_BY_DEFAULT
        return order_by

    def page_is_moved_handler(self):
        for item in self.items.all():
            item.save()

    @classmethod
    def get_item_model(cls):
        return cls._meta.get_field('items').related_model

    def get_item_queryset(self):
        return (self.get_item_model().objects.select_related('page')
                    .active()
                    .filter(self.get_filter())
                    .order_by(*self.get_order_by()))

    # filter section
    def get_filter(self):
        filter = models.Q(page=self)
        for field in self.FILTER_FIELDS:
            method = getattr(self, 'filter_%s' % getattr(self, field), None)
            if method and callable(method):
                filter &= method(filter)
        return filter

    def filter_date_req(self, filter):
        return models.Q(date_start__isnull=False)

    def filter_date_actual(self, filter):
        return models.Q(models.Q(date_start__lte=timezone.now()) |
                        models.Q(date_start__isnull=True))

    def filter_date_actual_both(self, filter):
        return models.Q(models.Q(date_start__lte=timezone.now()) |
                        models.Q(date_start__isnull=True),
                        models.Q(date_end__gte=timezone.now()) |
                        models.Q(date_end__isnull=True))

    def filter_date_anounce(self, filter):
        return models.Q(date_start__gte=timezone.now())


class BaseItem(models.Model):
    """A simple page's item model."""

    # page = models.ForeignKey(
    #     ItemPage, on_delete=models.CASCADE,
    #     related_name='items', verbose_name=_('page'))
    # brief = models.TextField(_('brief'), max_length=1024*20, blank=True)
    # text = models.TextField(_('text'), max_length=1024*200, blank=True)

    active = models.BooleanField(_('is active'), default=False, editable=False)
    published = models.BooleanField(_('is published'), default=True)
    visible = models.BooleanField(
        _('is visible'), default=True, help_text=_(
            'Show item in items list, also redirect if alone (visible?).'
        ))

    title = models.CharField(_('name'), max_length=2048)

    # dates
    date_start = models.DateTimeField(
        _('start date'), blank=True, null=True, db_index=True)
    date_end = models.DateTimeField(
        _('end date'), blank=True, null=True, db_index=True)

    # path
    slug = models.SlugField(_('slug'), max_length=255, db_index=True)
    url = models.CharField(_('url'), max_length=512, blank=True)

    weight = models.IntegerField(_('sorting weight'), default=500)

    # behaviour
    alt_template = models.CharField(
        _('alternative template'), max_length=128, blank=True,
        help_text=_('Template to render the content instead original.'))
    alt_view = models.CharField(
        _('alternative view'), max_length=128, blank=True,
        help_text=_('Alternative view for item detail view.'))

    show_item_name = models.BooleanField(
        _('show item name'), default=True,
        help_text=_('Show item name, usually in h2 tag (name?).'))
    show_node_link = models.BooleanField(
        _('show link to node'), default=True,
        help_text=_('Show link to parent node (to list?).'))
    show_in_meta = models.BooleanField(
        _('show in meta'), default=True,
        help_text=_('show item name in meta title and chain (meta?).'))

    # stat info
    date_create = models.DateTimeField(editable=False, auto_now_add=True)
    date_update = models.DateTimeField(editable=False, auto_now=True)

    objects = ItemManager()

    class Meta:
        verbose_name = _('item')
        verbose_name_plural = _('items')
        ordering = ('-date_start', '-weight', '-id',)
        abstract = True

    def __str__(self):
        return self.title

    def get_absolute_url(self, use_url=True):
        if use_url and self.url:
            return self.url

        meta = self.page.get_base_model()._meta
        path, url = self.page.get_path_or_url()
        view_name = self.page.view_name.format(app_label=meta.app_label,
                                               model_name=meta.model_name)
        path = '%s/%s' % (path, self.slug,) if path else '/404/'
        return reverse(view_name, kwargs={'path': path,})

    def get_absolute_url_real(self):
        return self.get_absolute_url(use_url=False)

    def get_active(self):
        return self.published and self.page.active

    @transaction.atomic
    def save(self, **kwargs):
        self.active = self.get_active()
        super().save(**kwargs)
