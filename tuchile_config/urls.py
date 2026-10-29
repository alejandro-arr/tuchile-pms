from django.contrib import admin
from django.urls import path
from pms import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("", views.dashboard_gantt, name="dashboard_gantt"),
    path("reservas/", views.reservas_lista, name="reservas_lista"),
    path("reservas/nueva/", views.crear_reserva, name="crear_reserva"),
    path("reservas/<int:reserva_id>/anular/", views.anular_reserva, name="anular_reserva"),
    path("reservas/<int:reserva_id>/checkin/", views.checkin_view, name="checkin_view"),
    path("reservas/<int:reserva_id>/checkout/", views.checkout_view, name="checkout_view"),
    path("reservas/<int:reserva_id>/comprobante/", views.comprobante_pago, name="comprobante_pago"),
    path("aseo/", views.aseo_movil, name="aseo_movil"),
    path("finanzas/", views.caja_reportes, name="caja_reportes"),
    path("finanzas/exportar-excel/", views.exportar_excel, name="exportar_excel"),
    path("mantenedores/", views.mantenedores_panel, name="mantenedores_panel"),
]
