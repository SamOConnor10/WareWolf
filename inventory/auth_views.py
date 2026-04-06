from django.contrib.auth.views import LoginView

from .forms import EmailOrUsernameAuthenticationForm
from .login_redirect import get_post_login_redirect_url


class WareWolfLoginView(LoginView):
    template_name = "registration/login.html"
    authentication_form = EmailOrUsernameAuthenticationForm

    def get_success_url(self):
        redirect_to = self.get_redirect_url()
        if redirect_to:
            return redirect_to
        return get_post_login_redirect_url(self.request.user)
