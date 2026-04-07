from django.urls import path, reverse
from django.shortcuts import redirect
from . import views

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("logout/", views.logout_view, name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("items/<int:pk>/forecast/", views.item_forecast, name="item_forecast"),
    path("anomalies/run/", views.run_anomaly_scan_view, name="run_anomaly_scan"),
    path(
        "anomalies/banner/dismiss/",
        views.dismiss_anomaly_scan_banner,
        name="dismiss_anomaly_scan_banner",
    ),
    path("anomalies/", views.anomaly_list, name="anomaly_list"),
    path("anomalies/<int:pk>/dismiss/", views.anomaly_dismiss, name="anomaly_dismiss"),
    path("anomalies/<int:pk>/review/", views.anomaly_review, name="anomaly_review"),
    path("anomalies/<int:pk>/undismiss/", views.anomaly_undismiss, name="anomaly_undismiss"),
    path("anomalies/bulk/review/", views.anomaly_bulk_review, name="anomaly_bulk_review"),
    path("anomalies/bulk/dismiss/", views.anomaly_bulk_dismiss, name="anomaly_bulk_dismiss"),
    path("anomalies/bulk/undismiss/", views.anomaly_bulk_undismiss, name="anomaly_bulk_undismiss"),
    path("search/", views.global_search, name="global_search"),

    path("manager-requests/<int:request_id>/approve/", views.approve_manager_request, name="approve_manager_request"),
    path("manager-requests/<int:request_id>/decline/", views.decline_manager_request, name="decline_manager_request"),

    path("notifications/<int:notification_id>/dismiss/", views.dismiss_notification, name="dismiss_notification"),
    path("alerts/dismiss/", views.dismiss_alert, name="dismiss_alert"),
    path("alerts/dismiss-bulk/", views.dismiss_alerts_bulk, name="dismiss_alerts_bulk"),
    path("alerts/", views.alerts_list, name="alerts_list"),
    

    # Stock CRUD
    path("items/", views.item_list, name="item_list"),
    path("items/decode-barcode/", views.decode_barcode_upload, name="decode_barcode_upload"),
    path("items/create/", views.item_create, name="item_create"),
    path("items/<int:pk>/", views.item_detail, name="item_detail"),
    path("items/<int:pk>/edit/", views.item_edit, name="item_edit"),
    path("items/<int:pk>/delete/", views.item_delete, name="item_delete"),
    path("items/<int:pk>/adjust/", views.item_adjust_quantity, name="item_adjust"),
    path("items/export/csv/", views.item_export_csv, name="item_export_csv"),
    path("items/<int:pk>/archive/", views.item_toggle_archive, name="item_toggle_archive"),
    path("items/<int:pk>/hard-delete/", views.item_hard_delete, name="item_hard_delete"),
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
    path("locations/tree/", lambda r: redirect(reverse("location_list") + "?view=tree"), name="location_tree"),
    path("locations/export/csv/", views.location_export_csv, name="location_export_csv"),
    path("locations/<int:pk>/view/", views.location_view, name="location_view"),
    # Orders CRUD
    path("orders/", views.order_list, name="order_list"),
    path("orders/create/", views.order_create, name="order_create"),
    path("orders/<int:pk>/", views.order_detail, name="order_detail"),
    path("orders/<int:pk>/edit/", views.order_edit, name="order_edit"),
    path("orders/<int:pk>/duplicate/", views.order_duplicate, name="order_duplicate"),
    path("orders/<int:pk>/delete/", views.order_delete, name="order_delete"),
    path("orders/export/csv/", views.order_export_csv, name="order_export_csv"),
    path(
        "orders/<int:pk>/mark-delivered/",
        views.order_mark_delivered,
        name="order_mark_delivered",
    ),
    # CONTACTS (combined Suppliers + Customers) CRUD
    path("contacts/", views.contacts_list, name="contacts_list"),
    path("contacts/export/csv/", views.contact_export_csv, name="contact_export_csv"),
    path("contacts/add/supplier/", views.supplier_create, name="supplier_create"),
    path("contacts/add/customer/", views.client_create, name="client_create"),
    path("contacts/supplier/<int:pk>/", views.supplier_view, name="supplier_view"),
    path("contacts/supplier/<int:pk>/edit/", views.supplier_edit, name="supplier_edit"),
    path("contacts/customer/<int:pk>/", views.client_view, name="client_view"),
    path("contacts/customer/<int:pk>/edit/", views.client_edit, name="client_edit"),
    path("contacts/supplier/<int:pk>/delete/", views.supplier_delete, name="supplier_delete"),
    path("contacts/customer/<int:pk>/delete/", views.client_delete, name="client_delete"),

    path("profile/request-manager/", views.request_manager_upgrade, name="request_manager_upgrade"),
    path("profile/demote-staff/", views.demote_to_staff, name="demote_to_staff"),
    path("profile/password/", views.password_change_page_redirect, name="password_change"),
    path("profile/password/done/", views.password_change_done_redirect, name="password_change_done"),
    path("profile/", views.profile_view, name="profile"),
    path("settings/", views.settings_view, name="settings"),
    path("profile/activity/export/", views.export_activity_log, name="export_activity_log"),
    path("settings/privacy/export-account/", views.export_account_data, name="export_account_data"),

]