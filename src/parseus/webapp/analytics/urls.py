"""Module linking url patterns to a view for the analytics app."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.analytics_index, name="analytics"),
    path("analytics/<str:analytic_types>", views.analytics, name="analytics_type"),
    path(
        "analytic_user_input/<int:analytic_pk>",
        views.update_analytic_user_input,
        name="update_analytic_user_input",
    ),
    path("train_model/", views.train_model, name="train_model"),
    path(
        "train_model/delete/<int:pk>/",
        views.delete_trained_model,
        name="delete_trained_model",
    ),
    path("get_models/<str:model_types>", views.get_trained_models, name="get_models"),
    path("predict_model/", views.predict_model, name="predict_model"),
    path(
        "predict_network_unsupervised/",
        views.predict_network_unsupervised,
        name="predict_unsupervised",
    ),
    path(
        "predict_peat_unsupervised/",
        views.predict_peat_unsupervised,
        name="predict_peat_unsupervised",
    ),
    path("push_results/", views.push_results, name="push_results"),
    path("peat_datasets/", views.peat_datasets, name="peat_datasets"),
]
