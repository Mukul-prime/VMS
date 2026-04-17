from django.db import models

# Create your models here.
class UserD(models.Model):
    Id = models.AutoField(primary_key=True)
    Name = models.CharField(max_length=100)
    Email = models.EmailField()
    Image = models.ImageField(upload_to='User/', null=True, blank=True)
    FaceEncoding = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "User"


