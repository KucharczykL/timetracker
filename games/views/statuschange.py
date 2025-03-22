from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from games.forms import GameStatusChangeForm
from games.models import GameStatusChange


class EditStatusChangeView(LoginRequiredMixin, UpdateView):
    model = GameStatusChange
    form_class = GameStatusChangeForm
    template_name = "add.html"
    context_object_name = "form"

    def get_object(self, queryset=None):
        return get_object_or_404(GameStatusChange, id=self.kwargs["statuschange_id"])

    def get_success_url(self):
        return reverse_lazy("list_platforms")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Edit Platform"
        return context


class AddStatusChangeView(LoginRequiredMixin, CreateView):
    model = GameStatusChange
    form_class = GameStatusChangeForm
    template_name = "add.html"

    def get_success_url(self):
        return reverse_lazy("view_game", kwargs={"pk": self.object.game.id})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Add status change"
        return context


class GameStatusChangeListView(LoginRequiredMixin, ListView):
    model = GameStatusChange
    template_name = "list_purchases.html"
    context_object_name = "status_changes"
    paginate_by = 10

    def get_queryset(self):
        return GameStatusChange.objects.select_related("game").all()


class GameStatusChangeDeleteView(LoginRequiredMixin, DeleteView):
    model = GameStatusChange
    template_name = "gamestatuschange_confirm_delete.html"

    def get_success_url(self):
        return reverse_lazy("view_game", kwargs={"game_id": self.object.game.id})
