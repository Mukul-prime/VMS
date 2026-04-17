from django.db import models

class ObjectsData(models.Model):
    Id = models.AutoField(primary_key=True)
    Name = models.TextField()

    class Meta:
        db_table = "Objects"
