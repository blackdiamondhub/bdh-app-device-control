from django.urls import path
from . import views

urlpatterns = [
    path('', views.device_control_view, name='device_control'),
    path('api/states/', views.device_control_states, name='device_control_states'),
    path('api/action/', views.device_control_action, name='device_control_action'),
    path('api/scenes/', views.device_control_scenes, name='device_control_scenes'),
    path('api/scenes/activate/', views.device_control_scene_action, name='device_control_scene_action'),
]
