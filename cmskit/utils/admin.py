import copy
from . import dicts_deep_merge


class FieldsetsDictMixin:
    """
    Mixin, that allows to simplify admin fieldsets definition and extending.
    Available values:
        - fieldsets_dict = None
          Stop extending further values, if it first in sequence,
          use django's fieldsets.

        - fieldsets_dict = {
              'name': {
                  'title': 'Title',
                  'fields': ('title', 'url',),
              },
              'text': {
                  'title': 'Text',
                  'fields': ('text', 'sign',),
                  'classes': ('collapse',),
              },
          }
          Common definition of fieldsets, 'title' key will be converted into
          django's fieldset title (first element of two-tuple value).

        - fieldsets_dict = {
              '**': False,
              'name': {
                  'title': 'Title',
                  'fields': ('title', 'url',),
              },
          }
          The definition of fieldsets with disallowed extending of ancestor's
          fieldsets_dict definitions. This value will extends only descendant's
          values, but can't be extended by ancestor's ones.
          By default '**' value is True.

    """

    def get_fieldsets(self, request, obj=None):
        fieldsets_dicts = [
            getattr(cls, 'fieldsets_dict', {}) for cls in type(self).__mro__
        ]
        if fieldsets_dicts:
            fieldsets_dicts = copy.deepcopy(fieldsets_dicts)
            fieldsets_dict, fieldsets = {}, []

            # merge all fieldsets_dicts from all ancestors by following rules:
            # - value is None or '**' value is False - stop further extending
            # - value is not empty - merge it with fieldsets_dict
            for fsdict in fieldsets_dicts:
                if fsdict is None:
                    break
                extend_parent_fieldsets = fsdict.pop('**', True)
                fieldsets_dict = dicts_deep_merge(fsdict, fieldsets_dict)
                if not extend_parent_fieldsets:
                    break

            # convert dict to django's builtin fieldsets format
            if fieldsets_dict:
                for key, data in fieldsets_dict.items():
                    if not 'fields' in data:
                        continue
                    fieldsets.append((data.pop('title', None), data,))

            if fieldsets:
                return fieldsets

        if self.fieldsets:
            return self.fieldsets

        return [(None, {'fields': self.get_fields(request, obj)})]
