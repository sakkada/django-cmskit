import re
from importlib import import_module
from functools import update_wrapper

from django import forms
from django.conf import settings
from django.contrib import admin
from django.contrib import messages
from django.contrib.admin import helpers
from django.contrib.admin.views.main import ERROR_FLAG
from django.contrib.admin.options import TO_FIELD_VAR, csrf_protect_m
from django.contrib.admin.exceptions import DisallowedModelAdminToField
from django.contrib.admin.utils import quote, unquote
from django.contrib.admindocs.views import extract_views_from_urlpatterns
from django.contrib.contenttypes.models import ContentType
from django.core import checks
from django.core.exceptions import ImproperlyConfigured
from django.forms.models import modelform_factory
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import ugettext_lazy as _
from django.utils.encoding import force_text
from django.urls import reverse, path
from django.urls.exceptions import NoReverseMatch

from cmskit.models import BasePage
from cmskit.utils.admin import FieldsetsDictMixin
from cmskit import conf


ERROR_VALUE_FOR_REDIRECT = 7


# Admin forms
# -----------
class BaseTargetFormMixin(forms.ModelForm):
    target_type = forms.ModelChoiceField(queryset=None, required=True)
    target_page = forms.ModelChoiceField(queryset=None, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        BaseModel = self.Meta.model.get_base_model()
        content_types = ContentType.objects.get_for_models(
            *BaseModel.get_page_models(), for_concrete_models=False
        )

        self.fields['target_type'].queryset = ContentType.objects.filter(
            id__in=[ct.id for model, ct in content_types.items()])
        self.fields['target_type'].label_from_instance = lambda obj: (
            '%s (%s)' % (obj, obj.model_class().__name__,)
        )
        self.fields['target_page'].queryset = BaseModel.objects.all()
        self.fields['target_page'].label_from_instance = lambda obj: (
            '%s%s (%s)' % ((obj.depth - 1) * '.. ',
                           obj, obj.specific_class.__name__,)
        )

    def clean_target_fields(self, cleaned_data):
        tt = cleaned_data.get('target_type', None)
        tp = cleaned_data.get('target_page', None)

        model = tt and tt.model_class()
        if model and not model.is_creatable:
            raise forms.ValidationError(
                _('Page with class "%(class)s" is not createble.') %
                model.__name__)
        if (model and model.max_count and
                model.objects.count() >= model.max_count):
            raise forms.ValidationError(
                _('Page with class "%(class)s" exceeded max_count'
                  ' instances limit (%(limit)d).') %
                {'class': model.__name__, 'limit': model.max_count,})
        if model and tt and tp and not model.can_create_at(tp):
            raise forms.ValidationError(
                _('Page with class "%(class)s" can not be created'
                  ' at page with class "%(parent_class)s", allowed parent'
                  ' page types are (%(parent_classes)s).') %
                {'class': model.__name__,
                 'parent_class': tp.specific_class.__name__,
                 'parent_classes': ', '.join(
                     i.__name__ for i in model.allowed_parent_page_models()
                 )})

        return cleaned_data


class BaseChoiceFieldsFormMixin(forms.ModelForm):
    choice_field_empty_label = '---------'
    choice_fields = {
        'behaviour': {'allow_empty': True,},
        'alt_template': {'allow_empty': True,},
        'base_template': {'allow_empty': False,},
        'url_name': {'allow_empty': True,},
        'menu_extender': {'allow_empty': True,},
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for name, conf in self.choice_fields.items():
            self.fields[name] = self.generate_choice_field(name, conf)

    def generate_choice_field(self, name, conf=None):
        conf = conf or self.choice_fields.get(name, None) or {}
        meta = self.Meta.model._meta
        return forms.ChoiceField(
            required=not conf.get('allow_empty', False),
            label=meta.get_field(name).verbose_name.capitalize(),
            choices=self.get_choices_for_field(name, conf),
            **conf.get('kwargs', {})
        )

    def get_choices_for_field(self, name, conf=None):
        conf = conf or self.choice_fields.get(name, None) or {}
        return (([('', self.choice_field_empty_label,),]
                 if conf.get('allow_empty', False) else []) +
                getattr(self, 'get_%s_choices' % name)())

    # choices getters
    def get_url_name_choices(self):
        urlconf = import_module(settings.ROOT_URLCONF)
        ignored = self.Meta.model.URL_NAME_IGNORED or ()
        choices = [
            (':'.join(ns + [name]), path)
            for func, path, ns, name in extract_views_from_urlpatterns(
                urlconf.urlpatterns)
            if name and not('(?P' in path or '<' in path)
        ]
        return [(name, '/%s (%s)' % (url, name)) for name, url in choices
                if not ignored or not any(re.match(i, name) for i in ignored)]

    def get_menu_extender_choices(self):
        try:
            from nodes.base import registry
            registry.autodiscover()
            return [(i, i,) for i in registry.menus.keys()]
        except ImportError:
            return []

    def get_base_template_choices(self):
        return [(i['code'], i['name'],) for i in conf.TEMPLATES]

    def get_alt_template_choices(self):
        return list(self.Meta.model.ALT_TEMPLATE_CHOICES) or []

    def get_behaviour_choices(self):
        return list(self.Meta.model.BEHAVIOUR_CHOICES) or []


class BasePageForm(BaseChoiceFieldsFormMixin, BaseTargetFormMixin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['target_page'].widget = forms.HiddenInput()
        self.fields['target_type'].widget = forms.HiddenInput()
        if self.instance.pk:
            self.fields['target_type'].required = False

    def clean(self):
        cleaned_data = super().clean()
        cleaned_data = self.clean_target_fields(cleaned_data)
        return cleaned_data


class BasePagePrepareForm(BaseTargetFormMixin):
    class Meta:
        fields = ('target_type', 'target_page',)
        admin_fieldsets = [(None, {'fields': fields,})]
        admin_readonly_fields = ()

    def clean(self):
        cleaned_data = super().clean()
        cleaned_data = self.clean_target_fields(cleaned_data)
        return cleaned_data


# Admin classes
# -------------
class BasePageAdmin(FieldsetsDictMixin, admin.ModelAdmin):
    prepare_template = None
    prepare_form = BasePagePrepareForm

    prepopulated_fields = {'slug': ('title',)}

    form = BasePageForm
    fieldsets_dict = {
        'main': {
            'fields': (
                'title', ('active', 'published',), 'base_template',
             ),
        },
        'path': {
            'title': _('Path settings'),
            'fields': (
                'slug', 'url_name', 'url_text', 'url_path',
                'target_type', 'target_page',
            ),
        },
        'menu': {
            'title': _('Menu settings'),
            'classes': ('collapse',),
            'fields': (
                'menu_weight', 'menu_title', 'menu_extender',
                'menu_in', 'menu_in_chain', 'menu_jump',
                'menu_login_required', 'menu_show_current',
            ),
        },
        'behaviour': {
            'title': _('Behaviour settings'),
            'classes': ('collapse',),
            'fields': ('behaviour', 'alt_template', 'alt_view',),
        },
        'readonly': {
            'title': _('Readonly fields'),
            'classes': ('collapse',),
            'fields': (
                'parent', 'content_type', 'owner',
                'depth', 'path', 'numchild',
                'slug_path', 'url_path', 'active',
                'date_create', 'date_update',
            ),
        },
    }
    readonly_fields = (
        'parent', 'content_type', 'owner', 'depth', 'path', 'numchild',
        'slug_path', 'url_path', 'active', 'date_create', 'date_update',)

    def check(self, **kwargs):
        errors = super().check(**kwargs)
        errors.extend(self._check_model_is_base_page(**kwargs))
        return errors

    def _check_model_is_base_page(self, **kwargs):
        if issubclass(self.model, BasePage):
            return []
        return [
            checks.Error(
                'PageAdmin works only with subclasses of BasePage model.',
                'Register PageAdmin class only with BasePage subclasses.',
                obj=self.model, id='cmskitadmin.E001',
            )
        ]

    def get_admin_url_for_model(self, model, action, args=None):
        try:
            return reverse(
                'admin:%s_%s_%s' % (
                    model._meta.app_label, model._meta.model_name, action,),
                args=args, current_app=self.admin_site.name,
            )
        except NoReverseMatch as e:
            raise NoReverseMatch(
                '%s Ensure you have registered %s class in admin interface.'
                % (e, model.__name__,)
            ) if issubclass(model, BasePage) else e

    @csrf_protect_m
    def changelist_view(self, request, extra_context=None):
        e = request.GET.get(ERROR_FLAG, None)
        e = int(e) if e and e.isdigit() else e
        base_model = self.model.get_base_model()

        if e == ERROR_VALUE_FOR_REDIRECT and not self.model is base_model:
            url = self.get_admin_url_for_model(base_model, 'changelist')
            return redirect(url)

        return super().changelist_view(request, extra_context=extra_context)

    def changeform_view(self, request, object_id=None,
                        form_url='', extra_context=None):

        base_model = self.model.get_base_model()

        content_type = request.POST.get(
            'target_type', request.GET.get('target_type', None)) or None
        content_type = ContentType.objects.filter(id=content_type).first()

        parent_id = request.POST.get(
            'target_page', request.GET.get('target_page', None)) or None
        parent = base_model.objects.filter(id=parent_id).first()
        parent = parent.specific if parent else None

        msg, url = None, None
        if not object_id:
            if not content_type:
                url = '%s?target_type=%s' % (
                    self.get_admin_url_for_model(base_model, 'prepare'),
                    ContentType.objects.get_for_model(self.model).id)
            elif not issubclass(content_type.model_class(), base_model):
                msg = _('ContentType "%s" is not subclass of base Page.'
                        ' It should be one of Page classes.') % content_type
                url = self.get_admin_url_for_model(base_model, 'prepare')
            elif content_type.model_class() is not self.model:
                msg = _('Page type "%s" does not match admin model class'
                        ' "%s".') % (content_type, self.model.__name__,)
                url = '%s?target_type=%s' % (
                    self.get_admin_url_for_model(base_model, 'prepare'),
                    content_type.id)
            elif parent_id and not parent:
                msg = _('Invalid "target_page" value, page does not exist.')
                url = '%s?target_type=%s' % (
                    self.get_admin_url_for_model(base_model, 'prepare'),
                    content_type.id)
            elif parent and not self.model.can_create_at(parent):
                msg = _('Page type "%s" can not be created in "%s" parent'
                        ' page.') % (self.model.__name__, parent,)
                url = '%s?target_type=%s' % (
                    self.get_admin_url_for_model(base_model, 'prepare'),
                    content_type.id)
            elif not content_type.model_class().is_creatable:
                msg = _('Page type "%s" can not be created manually'
                        ' in admin interface.') % content_type
                url = self.get_admin_url_for_model(base_model, 'prepare')
            elif (self.model.max_count and
                    self.model.objects.count() >= self.model.max_count):
                msg = _('Page type "%s" exceeded max_count instances limit'
                        ' (%d).') % (self.model.__name__, self.model.max_count,)
                url = self.get_admin_url_for_model(base_model, 'prepare')
        else:
            to_field = request.POST.get(TO_FIELD_VAR,
                                        request.GET.get(TO_FIELD_VAR))
            if to_field and not self.to_field_allowed(request, to_field):
                raise DisallowedModelAdminToField(
                    "The field %s can not be referenced." % to_field)

            # redirect if concrete type of obj and admin model do not match
            obj = self.get_object(request, unquote(object_id), to_field)
            obj = obj.specific if obj else None
            if obj and type(obj) is not self.model:
                url = '%s?_changelist_filters=e%%3D%s' % (
                    self.get_admin_url_for_model(
                        type(obj), 'change', args=(quote(obj.pk),)),
                    ERROR_VALUE_FOR_REDIRECT)

        if msg:
            self.message_user(request, msg, messages.ERROR)
        if url:
            return redirect(url)

        return super().changeform_view(
            request, object_id=object_id, form_url=form_url,
            extra_context=extra_context)

    def get_urls(self):
        urls = super().get_urls()
        if not issubclass(self.model, BasePage):
            return urls

        def wrap(view):
            def wrapper(*args, **kwargs):
                return self.admin_site.admin_view(view)(*args, **kwargs)
            wrapper.model_admin = self
            return update_wrapper(wrapper, view)

        info = self.model._meta.app_label, self.model._meta.model_name
        base_model = self.model.get_base_model()
        if base_model is self.model:
            my_urls = [
                path('prepare/', wrap(self.prepare_view),
                     name='%s_%s_prepare' % info),
            ]
            urls = my_urls + urls

        return urls

    @csrf_protect_m
    def prepare_view(self, request, extra_context=None):
        model, opts = self.model, self.model._meta
        base_model = model.get_base_model()

        if not self.has_add_permission(request):
            raise PermissionDenied

        Form = modelform_factory(base_model, form=self.prepare_form)
        form = Form(request.POST or None, initial=request.GET)
        if form.is_valid():
            tt = form.cleaned_data.get('target_type')
            tp = form.cleaned_data.get('target_page', None)

            url = self.get_admin_url_for_model(tt.model_class(), 'add')
            tail = '?target_type=%s' % tt.id
            if tp:
                tail += '&target_page=%s' % tp.id
            if ct.model_class() is not base_model:
                tail += '&_changelist_filters=e%%3D%s' % ERROR_VALUE_FOR_REDIRECT

            return redirect(url + tail)

        adminForm = helpers.AdminForm(
            form, form.Meta.admin_fieldsets, {},
            form.Meta.admin_readonly_fields, model_admin=self)

        context = dict(self.admin_site.each_context(request), **{
            'title': _('Prepare form for %s') % force_text(opts.verbose_name),
            'adminform': adminForm,
            'opts': opts,
            'media': self.media + adminForm.media,
            'errors': helpers.AdminErrorList(form, []),
        })
        context.update(extra_context or {})

        request.current_app = self.admin_site.name
        return TemplateResponse(request, self.prepare_template or [
            "admin/%s/%s/prepare_form.html" % (opts.app_label, opts.model_name),
            "admin/%s/prepare_form.html" % opts.app_label,
            "admin/prepare_form.html"
        ], context)

    def save_model(self, request, obj, form, change):
        if obj.pk is None:
            # TreeBeard api requires reloading new model from db after adding
            page = type(obj).add_root(instance=obj)
            page = type(obj).objects.filter(pk=page.pk).first()
            page.owner = request.user
            page.save(update_fields=['owner'])

            parent = form.cleaned_data.get('target_page', None)
            if parent:
                page.move(type(parent).objects.filter(pk=parent.pk).first(),
                          'last-child')
        else:
            obj.save()
