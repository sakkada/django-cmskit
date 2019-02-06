from django.db import models


class ItemQuerySet(models.QuerySet):
    def active(self):
        return self.filter(active=True)

    def visible(self):
        return self.filter(visible=True)


class ItemManager(models.Manager):
    queryset_class = ItemQuerySet

    def get_queryset(self):
        return self.queryset_class(self.model, using=self._db)

    def active(self):
        return self.get_queryset().active()

    def visible(self):
        return self.get_queryset().visible()
