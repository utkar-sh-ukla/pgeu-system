from django import forms
from django.core.exceptions import ValidationError
from postgresqleu.confsponsor.backendforms import BackendSponsorshipLevelBenefitForm

from .base import BaseBenefit, BaseBenefitForm


class BadgeScanningForm(BaseBenefitForm):
    confirm = forms.ChoiceField(label="Claim benefit", choices=((0, '* Choose'), (1, 'Claim this benefit'), (2, 'Decline this benefit')))

    def clean_confirm(self):
        if not int(self.cleaned_data['confirm']) in (1, 2):
            raise ValidationError('You must decide if you want to claim this benefit')
        return self.cleaned_data['confirm']


class BadgeScanning(BaseBenefit):
    @classmethod
    def get_backend_form(self):
        return BackendSponsorshipLevelBenefitForm

    def generate_form(self):
        return BadgeScanningForm

    def save_form(self, form, claim, request):
        if int(form.cleaned_data['confirm']) == 2:
            # This is actually a deny
            claim.declined = True
            claim.confirmed = True
            return True

        return True

    def can_unclaim(self, claimedbenefit):
        return True

    def render_claimdata(self, claimedbenefit, isadmin):
        if claimedbenefit.declined:
            return ""
        if claimedbenefit.confirmed:
            return 'To manage your badge scanning and results, please click <a href="/events/sponsor/{0}/scanning/">here</a>.'.format(
                claimedbenefit.sponsor.id,
            )
        else:
            return ""
