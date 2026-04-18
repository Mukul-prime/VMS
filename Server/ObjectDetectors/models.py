from django.db import models

from Camera.models import CreateCamera


# Create your models here.
class ObjectDetector(models.Model):
    Id = models.AutoField(primary_key=True)
    Name = models.CharField(max_length=100)

    class Meta:
        db_table = "ObjectDetectors"


class ObjectCount(models.Model):
    Id = models.AutoField(primary_key=True)
    ObjectRef = models.ForeignKey(
        ObjectDetector,
        on_delete=models.CASCADE,
        related_name="counts",
    )
    CamRef = models.ForeignKey(
        CreateCamera,
        on_delete=models.CASCADE,
        related_name="object_counts",
    )
    Count = models.IntegerField(default=0)
    UpdatedAt = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ObjectCounts"
        unique_together = ("ObjectRef", "CamRef")
        

class verify_data(models.Model):
    Id = models.AutoField(primary_key=True)
    ObjectRef = models.ForeignKey(
        ObjectDetector,
        on_delete=models.CASCADE,
        related_name="verify_data",
    )
    CamRef = models.ForeignKey(
        CreateCamera,
        on_delete=models.CASCADE,
        related_name="verify_data",
    )
    Verified = models.BooleanField(default=False)
    count = models.IntegerField(default=0)