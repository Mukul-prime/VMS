from django.db import models

# Create your models here.
class CreateCamera(models.Model):
    Cam_id = models.AutoField(primary_key=True)
    Cam_name = models.CharField(max_length=100)
    Cam_location = models.CharField(max_length=100)
    ip_address = models.CharField(max_length=100)
    rstp_url = models.CharField(max_length=100)
    username = models.CharField(max_length=100)
    password = models.CharField(max_length=100)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "Cameras"



class Persons(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    date = models.DateField(null=True, blank=True)

    count = models.IntegerField(default=0)   # 🔥 ADD THIS

    Cam_ids = models.ForeignKey(
        CreateCamera,
        on_delete=models.CASCADE
    )

    class Meta:
        db_table = "Persons"
        unique_together = ('Cam_ids', 'date')

    def __str__(self):
        return f"{self.Cam_ids} | {self.date} | {self.count}"



#
# class Objects(models.Model):
#     Id = models.AutoField(primary_key=True)
#     created = models.DateTimeField(auto_now_add=True)
#     count = models.IntegerField(default=0)
#
#
#
#     class Meta:
#         db_table = "ObjectsPhaser"

