from django.apps import apps
from django.db.models import Model


def jump_node_by_node(node):
    """search target node from node with menu_jump"""
    node_from, node_to = node, None
    while True:
        if node_from.menu_jump:
            qset = list(node_from.children.filter(active=True)[:1])
            node_to = qset and qset[0] or node_to
        if node_to and node_to.menu_jump:
            node_from, node_to = node_to, None
        else:
            if not node_to and node_from != node:
                node_to = node_from
            break
    return node_to


def resolve_model_string(model_string, default_app=None):
    """
    Resolve an 'app_label.model_name' string into an actual model class.
    If a model class is passed in, just return that.

    Raises a LookupError if a model can not be found, or ValueError if passed
    something that is neither a model or a string.
    """
    if isinstance(model_string, str):
        try:
            app_label, model_name = model_string.split(".")
        except ValueError:
            if default_app is not None:
                # If we can't split, assume a model in current app
                app_label = default_app
                model_name = model_string
            else:
                raise ValueError(
                    'Can not resolve {0!r} into a model. Model names should '
                    'be in the form app_label.model_name'.format(model_string),
                    model_string)

        return apps.get_model(app_label, model_name)

    elif isinstance(model_string, type) and issubclass(model_string, Model):
        return model_string

    else:
        raise ValueError(
            'Can not resolve {0!r} into a model'.format(model_string),
            model_string)
