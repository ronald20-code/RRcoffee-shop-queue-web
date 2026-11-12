from django.urls import path

from . import manage_views, views

app_name = "kiosk"

urlpatterns = [
    path("home/", views.home, name="home"),
    path("", views.menu, name="menu"),
    path("menu/version.json", views.menu_version, name="menu_version"),
    path("order/place/", views.place_order, name="place_order"),
    path("pay/<int:pk>/", views.pay, name="pay"),
    path("order/<int:pk>/", views.order_status, name="order_status"),
    path("order/<int:pk>/status.json", views.order_status_api, name="order_status_api"),
    path("my-orders/", views.my_orders, name="my_orders"),
    path("kitchen/", views.kitchen, name="kitchen"),
    path("kitchen/orders.json", views.kitchen_api, name="kitchen_api"),
    path("kitchen/update/<int:pk>/", views.kitchen_update, name="kitchen_update"),
    path("board/", views.board, name="board"),
    path("board.json", views.board_api, name="board_api"),
    # admin (superuser) menu manager
    path("manage/menu/", manage_views.menu_manager, name="manage_menu"),
    path("manage/menu/new/", manage_views.product_create, name="product_create"),
    path("manage/menu/<int:pk>/edit/", manage_views.product_edit, name="product_edit"),
    path("manage/menu/<int:pk>/delete/", manage_views.product_delete, name="product_delete"),
    path("manage/menu/<int:pk>/quick/", manage_views.product_quick, name="product_quick"),
    path("manage/menu/<int:pk>/remove-photo/", manage_views.product_remove_photo, name="product_remove_photo"),
    path("manage/category/new/", manage_views.category_create, name="category_create"),
    path("manage/category/<int:pk>/edit/", manage_views.category_edit, name="category_edit"),
    path("manage/category/<int:pk>/delete/", manage_views.category_delete, name="category_delete"),
    path("manage/category/<int:pk>/move/<str:direction>/", manage_views.category_move, name="category_move"),
]
