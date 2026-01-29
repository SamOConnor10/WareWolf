from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Supplier, Client, Location, Item

admin.site.register(Supplier)
admin.site.register(Client)
admin.site.register(Location)
admin.site.register(Item)
