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
