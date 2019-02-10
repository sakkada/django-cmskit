from django import forms
from django.contrib import admin
from django.contrib.admin.views.main import ERROR_FLAG
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import redirect
from functools import partial, reduce, update_wrapper
from django.template.response import SimpleTemplateResponse, TemplateResponse
from django.contrib.admin import helpers, widgets
from django.forms.models import (
    BaseInlineFormSet, inlineformset_factory, modelform_defines_fields,
    modelform_factory, modelformset_factory,
)
from django.utils.translation import ugettext_lazy as _
from django.utils.encoding import force_text


from django.contrib.admin.options import TO_FIELD_VAR
from django.contrib.admin.exceptions import DisallowedModelAdminToField
from django.core import checks


from django.contrib.admin.utils import (
    NestedObjects, construct_change_message, flatten_fieldsets,
    get_deleted_objects, lookup_needs_distinct, model_format_dict,
    model_ngettext, quote, unquote,
)
from django.urls import reverse, path
from django.contrib.admin.options import csrf_protect_m
from cmskit.models import BasePage


"""
FORM VIEW - if exists CMS ADMIN for model - redirect to it,
            else try to get FORM for model,
            else CREATE from for model.

LIST VIEW - if model is not ROOT, redirect to root
            (may be except e={some digit})
"""


class BasePageForm(forms.ModelForm):
    behaviour = forms.ChoiceField(required=False)
    alt_template = forms.ChoiceField(required=False)

    target_page = forms.ModelChoiceField(required=False, queryset=None, widget=forms.HiddenInput)
    target_type = forms.ModelChoiceField(required=False, queryset=None, widget=forms.HiddenInput)

    def get_template_patterns(self):
        import ipdb; ipdb.set_trace(context=20)
        pass

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        meta = self.Meta.model._meta

        self.fields['behaviour'].choices = (('', '---------',),) + self.Meta.model.BEHAVIOUR_CHOICES
        self.fields['behaviour'].label = meta.get_field('behaviour').verbose_name.capitalize()
        self.fields['alt_template'].choices = (('', '---------',),) + self.Meta.model.ALT_TEMPLATE_CHOICES
        self.fields['alt_template'].label = meta.get_field('alt_template').verbose_name.capitalize()

        ctlist = ContentType.objects.get_for_models(*self.Meta.model.get_base_model().get_page_models(), for_concrete_models=False).values()

        self.fields['target_page'].queryset = self.Meta.model.get_base_model().objects.all()
        self.fields['target_type'].queryset = ContentType.objects.filter(id__in=[i.id for i in ctlist])

    def clean(self):
        cleaned_data = super().clean()

        ct = cleaned_data.get('target_type', None)
        pp = cleaned_data.get('target_page', None)
        model = ct and ct.model_class()
        if model and not model.is_creatable:
            raise forms.ValidationError('Page with class "%s" is not createble.' % str(model.__name__))
        if model and model.max_count and model.objects.count() >= model.max_count:
            raise forms.ValidationError('Page with class "%s" exceeded max_count limit (%d).' % str(model.__name__, model.max_count,))
        if ct and pp and not model.can_create_at(pp):
            raise forms.ValidationError('Page with class "%s" con not be created at page with class "%s".' % (str(ct.model_class().__name__), str(type(pp).__name__),))

        return cleaned_data



class BasePagePrepareForm(forms.ModelForm):
    target_type = forms.ModelChoiceField(queryset=None, required=True)
    target_page = forms.ModelChoiceField(queryset=None, required=False)

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)

        super().__init__(*args, **kwargs)

        meta = self.Meta.model._meta

        ctlist = ContentType.objects.get_for_models(*self.Meta.model.get_page_models(), for_concrete_models=False).values()
        self.fields['target_type'].queryset = ContentType.objects.filter(id__in=[i.id for i in ctlist])
        self.fields['target_type'].label_from_instance = lambda obj: str(obj) + ' (%s)' % str(obj.model_class().__name__)
        self.fields['target_page'].queryset = self.Meta.model.objects.all()
        self.fields['target_page'].label_from_instance = lambda obj: (obj.depth-1) * '.. ' + str(obj) + ' (%s)' % str(type(obj.specific).__name__)

    class Meta:
        fields = ('target_type', 'target_page',)
        admin_fieldsets = [(None, {'fields': fields,})]
        admin_readonly_fields = tuple(),

    def clean(self):
        cleaned_data = super().clean()

        ct = cleaned_data.get('target_type', None)
        pp = cleaned_data.get('target_page', None)
        model = ct and ct.model_class()
        if model and not model.is_creatable:
            raise forms.ValidationError('Page with class "%s" is not createble.' % str(model.__name__))
        if model and model.max_count and model.objects.count() >= model.max_count:
            raise forms.ValidationError('Page with class "%s" exceeded max_count limit (%d).' % (str(model.__name__), model.max_count,))
        if ct and pp and not model.can_create_at(pp):
            raise forms.ValidationError('Page with class "%s" con not be created at page with class "%s", allowed parent page types are (%s).' % (str(ct.model_class().__name__), str(pp.specific_class.__name__),
                ', '.join([str(i.__name__) for i in ct.model_class().allowed_parent_page_models()]),))

        return cleaned_data


class BasePageAdmin(admin.ModelAdmin):
    form = BasePageForm
    exclude = ('depth', 'content_type', 'numchild', 'path',)

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
        form = Form(request.POST or None, user=request.user, initial=request.GET)
        if form.is_valid():
            #self.message_user(request, format_html(
            #    _('The balance of "{obj}" was changed successfully.'),
            #    **{'obj': force_text(obj),}), messages.SUCCESS)
            ct = form.cleaned_data.get('target_type')
            pp = form.cleaned_data.get('target_page', None)
            url = self.get_admin_url_for_specific_type(ct.model_class(), 'add')
            tail = '?target_page=%s&target_type=%s' % (pp.id if pp else 0, ct.id,)
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
            page = type(obj).add_root(instance=obj)
            parent = form.cleaned_data.get('target_page', None)
            if parent:
                type(page).objects.filter(pk=page.pk).first().move(
                    type(parent).objects.filter(pk=parent.pk).first(),
                    'last-child')
        else:
            obj.save()
