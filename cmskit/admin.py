import re
from importlib import import_module
from functools import update_wrapper

from django import forms
from django.conf import settings
from django.contrib import admin
from django.contrib.admin.views.main import ERROR_FLAG
from django.contrib.admin import helpers
from django.contrib.admin.options import TO_FIELD_VAR
from django.contrib.admin.exceptions import DisallowedModelAdminToField
from django.contrib.admin.utils import quote, unquote
from django.contrib.admin.options import csrf_protect_m
from django.contrib.admindocs.views import extract_views_from_urlpatterns
from django.contrib.contenttypes.models import ContentType
from django.core import checks
from django.forms.models import modelform_factory
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import ugettext_lazy as _
from django.utils.encoding import force_text
from django.urls import reverse, path

from cmskit.models import BasePage
from cmskit.utils.admin import FieldsetsDictMixin
from cmskit import conf


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

        self.fields['target_page'].queryset = BaseModel.objects.all()
        self.fields['target_page'].label_from_instance = lambda obj: (
            '%s%s (%s)' % ((obj.depth - 1) * '.. ',
                           obj, obj.specific_class.__name__,)
        )
        self.fields['target_type'].queryset = ContentType.objects.filter(
            id__in=[ct.id for model, ct in content_types.items()])
        self.fields['target_type'].label_from_instance = lambda obj: (
            '%s (%s)' % (obj, obj.model_class().__name__,)
        )

    def clean_target_fields(self, cleaned_data):
        tt = cleaned_data.get('target_type', None)
        tp = cleaned_data.get('target_page', None)

        model = tt and tt.model_class()
        if model and not model.is_creatable:
            raise forms.ValidationError(
                _('Page with class "%(class)s" is not createble.') %
                model.__name__)
        if model and model.objects.count() >= (model.max_count or 0) > 0:
            raise forms.ValidationError(
                _('Page with class "%(class)s" exceeded max_count'
                  ' instances limit (%(limit)d).') %
                {'class': model.__name__, 'max_count': model.max_count})
        if model and tt and tp and not model.can_create_at(tp):
            raise forms.ValidationError(
                _('Page with class "%(class)s" con not be created'
                  'at page with class "%(parent_class)s", allowed parent'
                  ' page types are (%(parent_classes)s).') %
                {'class': model.__name__,
                 'parent_class': tp.specific_class.__name__,
                 'parent_classes': ', '.join(
                     i.__name__ for i in model.allowed_parent_page_models())})

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
        except ImportError:
            return []
        registry.autodiscover()
        return [(i, i,) for i in registry.menus.keys()]

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
    prepopulated_fields = {'slug': ('title',)}

    form = BasePageForm
    readonly_fields = (
        'parent', 'content_type', 'owner', 'depth', 'path', 'numchild',
        'slug_path', 'url_path', 'active', 'date_create', 'date_update',)

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

    # todo: to be refactored
    def get_admin_url_for_specific_type(self, model, action, args=None):
        opts = model._meta
        obj_url = reverse(
            'admin:%s_%s_%s' % (opts.app_label, opts.model_name, action,),
            args=args, current_app=self.admin_site.name,
        )
        return obj_url

    def changeform_view(self, request,
                        object_id=None, form_url='', extra_context=None):

        """
        object_id is None:
        - if base_model - select type and parent
        - else          - create object

        object_id is not None
        - model mismatches object - redirect to respective admin or to base model
        - model mathces object    - work as usual
        """
        base_model = self.model.get_base_model()

        content_type = request.GET.get('target_type', '') or request.POST.get('target_type', '')
        content_type = int(content_type) if content_type.isdigit() else None
        content_type = ContentType.objects.filter(id=content_type).first()

        parent = request.GET.get('target_page', '') or request.POST.get('target_page', '')
        parent_id = int(parent) if parent.isdigit() else None
        parent = base_model.objects.filter(id=parent_id).first()
        parent = parent.specific if parent else None

        # raise
        if not object_id:
            if base_model is self.model:
                if not content_type:
                    url = self.get_admin_url_for_specific_type(base_model, 'prepare')
                    return redirect(url + '?target_type=%s' % ContentType.objects.get_for_model(self.model).id)
                if not content_type.model_class() is self.model:
                    url = self.get_admin_url_for_specific_type(content_type.model_class(), 'add')
                    return redirect(url + '?_changelist_filters=e%3D7')

                if not issubclass(content_type.model_class(), base_model):
                    raise Exception('CT is not subclass of base Page.')
            else:
                if not content_type:
                    url = self.get_admin_url_for_specific_type(base_model, 'prepare')
                    return redirect(url + '?target_type=%s' % ContentType.objects.get_for_model(self.model).id)
                if not content_type.model_class() is self.model:
                    raise Exception('CT and models is not match.')

            if parent_id and not parent:
                raise Exception('Invalid PID')
            if not content_type.model_class().is_creatable:
                raise Exception('Type is not creatable')
            if content_type.model_class().max_count and content_type.model_class().objects.count() >= content_type.model_class().max_count:
                raise Exception('Type\'s max_count limit is exceeded.')
            if parent and not content_type.model_class().can_create_at(parent):
                raise Exception('Invalid PARENT')

        else:
            to_field = request.POST.get(TO_FIELD_VAR, request.GET.get(TO_FIELD_VAR))
            if to_field and not self.to_field_allowed(request, to_field):
                raise DisallowedModelAdminToField("The field %s cannot be referenced." % to_field)

            obj = self.get_object(request, unquote(object_id), to_field)
            obj = obj.specific if obj else None
            if obj and not type(obj) is self.model:
                if self.model is base_model:
                    url = self.get_admin_url_for_specific_type(type(obj), 'change', args=(quote(obj.pk),))
                    return redirect(url + '?_changelist_filters=e%3D7')


        return super().changeform_view(
            request, object_id=object_id, form_url=form_url,
            extra_context=extra_context)

    @csrf_protect_m
    def changelist_view(self, request, extra_context=None):
        e = request.GET.get(ERROR_FLAG, None)
        e = int(e) if e and e.isdigit() else e
        base_model = self.model.get_base_model()

        if e == 7 and not self.model is base_model:
            url = self.get_admin_url_for_specific_type(base_model, 'changelist')
            return redirect(url)

        return super().changelist_view(request, extra_context=extra_context)

    prepare_template = None
    prepare_form = BasePagePrepareForm

    @csrf_protect_m
    def prepare_view(self, request, extra_context=None):
        model, opts = self.model, self.model._meta
        base_model = model.get_base_model()

        if not self.has_add_permission(request):
            raise PermissionDenied

        Form = modelform_factory(base_model, form=self.prepare_form)
        form = Form(request.POST or None, initial=request.GET)
        if form.is_valid():
            #self.message_user(request, format_html(
            #    _('The balance of "{obj}" was changed successfully.'),
            #    **{'obj': force_text(obj),}), messages.SUCCESS)
            ct = form.cleaned_data.get('target_type')
            pp = form.cleaned_data.get('target_page', None)
            url = self.get_admin_url_for_specific_type(ct.model_class(), 'add')
            tail = '?target_page=%s&target_type=%s' % (pp.id if pp else '', ct.id,)
            if not base_model is ct.model_class():
                tail += '&_changelist_filters=e%3D7'
            return redirect(url + tail)

        adminForm = helpers.AdminForm(
            form, form.Meta.admin_fieldsets, {},
            form.Meta.admin_readonly_fields, model_admin=self)

        context = dict(self.admin_site.each_context(request), **{
            'title': _('Change balance of %s') % force_text(opts.verbose_name),
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

    def save_model(self, request, obj, form, change):
        """Given a model instance save it to the database."""
        if obj.pk is None:
            # each-time reloading required by treebeard api
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
