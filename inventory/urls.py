from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("search/", views.global_search, name="global_search"),

    # Stock CRUD
    path("items/", views.item_list, name="item_list"),
    path("items/create/", views.item_create, name="item_create"),
    path("items/<int:pk>/edit/", views.item_edit, name="item_edit"),
    path("items/<int:pk>/delete/", views.item_delete, name="item_delete"),
    path("items/<int:pk>/adjust/", views.item_adjust_quantity, name="item_adjust"),
    path("items/export/csv/", views.item_export_csv, name="item_export_csv"),
    # Categories CRUD
    path("categories/", views.category_list, name="category_list"),
    path("categories/add/", views.category_create, name="category_create"),
    path("categories/<int:pk>/edit/", views.category_edit, name="category_edit"),
    path("categories/<int:pk>/delete/", views.category_delete, name="category_delete"),
    path("categories/create-from-item/", views.category_create_from_item, name="category_create_from_item"),
    path("categories/ajax/add/", views.category_create_ajax, name="category_create_ajax"),
    # Location CRUD
    path("locations/", views.location_list, name="location_list"),
    path("locations/create/", views.location_create, name="location_create"),
    path("locations/<int:pk>/edit/", views.location_edit, name="location_edit"),
    path("locations/<int:pk>/delete/", views.location_delete, name="location_delete"),
    path("locations/tree/", views.location_tree, name="location_tree"),
    path("locations/<int:pk>/view/", views.location_view, name="location_view"),
    # Orders CRUD
    path("orders/", views.order_list, name="order_list"),
    path("orders/create/", views.order_create, name="order_create"),
    path("orders/<int:pk>/edit/", views.order_edit, name="order_edit"),
    path("orders/<int:pk>/delete/", views.order_delete, name="order_delete"),
    path(
        "orders/<int:pk>/mark-delivered/",
        views.order_mark_delivered,
        name="order_mark_delivered",
    ),
    # CONTACTS (combined Suppliers + Customers) CRUD
    path("contacts/", views.contacts_list, name="contacts_list"),
    path("contacts/add/supplier/", views.supplier_create, name="supplier_create"),
    path("contacts/add/customer/", views.client_create, name="client_create"),
    path("contacts/supplier/<int:pk>/edit/", views.supplier_edit, name="supplier_edit"),
    path("contacts/customer/<int:pk>/edit/", views.client_edit, name="client_edit"),
    path("contacts/supplier/<int:pk>/delete/", views.supplier_delete, name="supplier_delete"),
    path("contacts/customer/<int:pk>/delete/", views.client_delete, name="client_delete"),

]

