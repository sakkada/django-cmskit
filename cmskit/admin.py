from django import forms
from django.contrib import admin
from django.contrib.contenttypes.models import ContentType


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

    def get_template_patterns(self):
        import ipdb; ipdb.set_trace(context=20)
        pass

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # import ipdb; ipdb.set_trace(context=20)

        meta = self.Meta.model._meta


        self.fields['behaviour'].choices = (('', '---------',),) + self.Meta.model.BEHAVIOUR_CHOICES
        self.fields['behaviour'].label = meta.get_field('behaviour').verbose_name.capitalize()
        self.fields['alt_template'].choices = (('', '---------',),) + self.Meta.model.ALT_TEMPLATE_CHOICES
        self.fields['alt_template'].label = meta.get_field('alt_template').verbose_name.capitalize()


class PageBaseAdmin(admin.ModelAdmin):
    form = BasePageForm

    def get_object(self, request, object_id, from_field=None):
        obj = super().get_object(request, object_id, from_field=from_field)
        return obj.specific
        return obj#.specific

    def get_form(self, request, obj=None, change=False, **kwargs):
        if not obj:
            content_type = request.GET.get('t', '')
            content_type = int(content_type) if content_type.isdigit() else None
            content_type = ContentType.objects.filter(id=content_type).first()
            #if not content_type:
            #    raise Exception('REDIRECT TO CHOOSE POSITION 1')

            model_class = content_type.model_class() if content_type else self.model
            model_classes = self.model.get_page_models()
            if model_class not in model_classes:
                raise Exception('REDIRECT TO CHOOSE POSITION 2')
            if not model_class.is_creatable:
                raise Exception('REDIRECT TO CHOOSE POSITION 3')

            parent = request.GET.get('p', '')
            parent = int(parent) if parent.isdigit() else None
            parent = self.model.objects.filter(id=parent).first()
            parent = parent.specific if parent else None
            if parent and not model_class.can_create_at(parent):
                raise Exception('REDIRECT TO CHOOSE POSITION 4')
        else:
            obj = obj.specific
            model_class = type(obj)

        from collections import OrderedDict
        from functools import partial, reduce, update_wrapper
        from urllib.parse import quote as urlquote

        from django import forms
        from django.conf import settings
        from django.contrib import messages
        from django.contrib.admin import helpers, widgets
        from django.contrib.admin.checks import (
            BaseModelAdminChecks, InlineModelAdminChecks, ModelAdminChecks,
        )
        from django.contrib.admin.utils import flatten_fieldsets
        from django.contrib.auth import get_permission_codename
        from django.core.exceptions import (
            FieldError, ValidationError,
        )
        from django.core.paginator import Paginator
        from django.db import models, router, transaction
        from django.db.models.constants import LOOKUP_SEP
        from django.db.models.fields import BLANK_CHOICE_DASH
        from django.forms.formsets import DELETION_FIELD_NAME, all_valid
        from django.forms.models import (
            modelform_defines_fields, modelform_factory
        )


        if 'fields' in kwargs:
            fields = kwargs.pop('fields')
        else:
            fields = flatten_fieldsets(self.get_fieldsets(request, obj))
        excluded = self.get_exclude(request, obj)
        exclude = [] if excluded is None else list(excluded)
        readonly_fields = self.get_readonly_fields(request, obj)
        exclude.extend(readonly_fields)
        # Exclude all fields if it's a change form and the user doesn't have
        # the change permission.
        if change and hasattr(request, 'user') and not self.has_change_permission(request, obj):
            exclude.extend(fields)
        if excluded is None and hasattr(self.form, '_meta') and self.form._meta.exclude:
            # Take the custom ModelForm's Meta.exclude into account only if the
            # ModelAdmin doesn't define its own.
            exclude.extend(self.form._meta.exclude)
        # if exclude is an empty list we pass None to be consistent with the
        # default on modelform_factory
        exclude = exclude or None

        # Remove declared form fields which are in readonly_fields.
        new_attrs = OrderedDict.fromkeys(
            f for f in readonly_fields
            if f in self.form.declared_fields
        )
        form = type(self.form.__name__, (self.form,), new_attrs)

        defaults = {
            'form': form,
            'fields': fields,
            'exclude': exclude,
            'formfield_callback': partial(self.formfield_for_dbfield, request=request),
            **kwargs,
        }

        if defaults['fields'] is None and not modelform_defines_fields(defaults['form']):
            defaults['fields'] = forms.ALL_FIELDS

        try:
            return modelform_factory(model_class, **defaults)
        except FieldError as e:
            raise FieldError(
                '%s. Check fields/fieldsets/exclude attributes of class %s.'
                % (e, self.__class__.__name__)
            )

        # return super().get_form(request, obj=obj, change=change, **kwargs)

    def __changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        #    class PageInitialAdminForm(forms.ModelForm):
        #        #TYPE_CHOICES = (
        #        #    [(index, str(model.__name__),) for index, model in enumerate(self.model.get_page_models())]
        #        #)
        #        #content_type = forms.ChoiceField(choices=TYPE_CHOICES)
        #        parent = forms.ModelChoiceField(self.model.objects.all(), required=False)
        #
        #        class Meta:
        #            model = self.model
        #            # fields = ('type', 'parent',)
        #            fields = ('parent',)
        #
        #        def __init__(self, *args, **kwargs):
        #            #qq = [i.id for i in ContentType.objects.get_for_models(*self._meta.model.get_page_models(), for_concrete_models=False).values()]
        #            super().__init__(*args, **kwargs)
        #            #self.fields['content_type'].queryset = ContentType.objects.filter(
        #            #    id__in=qq)
        #
        #        def clean(self):
        #            raise forms.ValidationError('.')
        #
        #    return PageInitialAdminForm

        if not change:
            parent = request.GET.get('p', '')
            parent = int(parent) if parent.isdigit() else None
            content_type = request.GET.get('t', '')
            content_type = int(content_type) if content_type.isdigit() else None

            if content_type is None or parent is None:
                raise Exception('REDIRECT TO CHOOSE POSITION')

            if not parent:
                parent = None
            content_type = ContentType.objects.filter(id=content_type).first()
            if not content_type:
                raise Exception('REDIRECT TO CHOOSE POSITION 1')

            model_class = content_type.model_class()
            model_classes = self.model.get_page_models()
            if model_class not in model_classes:
                raise Exception('REDIRECT TO CHOOSE POSITION 2')
            if not model_class.is_creatable:
                raise Exception('REDIRECT TO CHOOSE POSITION 3')
            if parent and not model_class.can_create_at(parent):
                raise Exception('REDIRECT TO CHOOSE POSITION 4')

        content_type = request.GET.get('t', '')
        content_type = int(content_type) if content_type.isdigit() else None
        content_type = ContentType.objects.filter(id=content_type).first()
        model_class = content_type.model_class()

        if model_class in self.admin_site._registry:
            r = self.admin_site._registry[model_class].changeform_view(request, object_id=object_id, form_url=form_url, extra_context=extra_context)
        else:
            r = super().changeform_view(request, object_id=object_id, form_url=form_url, extra_context=extra_context)
        return r

        m = self.model
        self.model = model_class
        self.model = m


    def response_add(self, request, obj, post_url_continue=None):
        return super().response_add(
            request, obj.get_base_model().objects.filter(id=obj.id).first(), post_url_continue=post_url_continue
        )

    def response_change(self, request, obj):
        return super().response_change(
            request, obj.get_base_model().objects.filter(id=obj.id).first(),
        )

    #def get_initial_form_for_class(self, klass):
