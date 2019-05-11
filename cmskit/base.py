from . import conf


# exceptions
class TemplateAllreadyRegistered(Exception):
    pass


# registry
class Registry(object):
    def __init__(self):
        self.views = {}
        self.templates = {}
        self._models = None
        self.autoregister_by_conf()

    @property
    def models(self):
        if self._models is None:
            from cmskit.models import ti
            self._models = ti.TI_MODEL_CLASSES
        return self._models

    def autoregister_by_conf(self):
        if conf.TEMPLATES:
            for item in conf.TEMPLATES:
                self.register_template(item)

    def register_template(self, template):
        assert isinstance(template, dict)
        if not all(i in template for i in ['name', 'path',]):
            raise ValueError('Template dict is not correct.')
        if template['name'] in self.templates:
            raise TemplateAllreadyRegistered(template['name'])
        self.templates[template['name']] = template

    def unregister_template(self, name):
        self.templates.pop(name, None)

    def clear_templates(self):
        self.templates = {}

    def register_view(self, model, view, **kwargs):
        self.views[model] = view.as_view(page_model=model, **kwargs)

    def unregister_view(self, model):
        self.views.pop(model, None)

    def clear_views(self, model):
        self.views = {}


# registy singleton
registry = Registry()
