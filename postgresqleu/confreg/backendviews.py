from django.shortcuts import render, get_object_or_404
from django.db import transaction
from django import forms
from django.core import urlresolvers
from django.http import HttpResponseRedirect, Http404
from django.contrib.admin.utils import NestedObjects
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf import settings

import urllib
import datetime

from postgresqleu.util.middleware import RedirectException
from postgresqleu.util.db import exec_to_dict, exec_no_result

from models import Conference, ConferenceRegistration
from models import RegistrationType, RegistrationClass

from postgresqleu.invoices.models import Invoice

from backendforms import BackendCopySelectConferenceForm
from backendforms import BackendConferenceForm, BackendRegistrationForm
from backendforms import BackendRegistrationTypeForm, BackendRegistrationClassForm
from backendforms import BackendRegistrationDayForm, BackendAdditionalOptionForm
from backendforms import BackendTrackForm, BackendRoomForm, BackendConferenceSessionForm
from backendforms import BackendConferenceSessionSlotForm, BackendVolunteerSlotForm
from backendforms import BackendFeedbackQuestionForm, BackendDiscountCodeForm

def get_authenticated_conference(request, urlname):
	if not request.user.is_authenticated:
		raise RedirectException("{0}?{1}".format(settings.LOGIN_URL, urllib.urlencode({'next': request.build_absolute_uri()})))

	if request.user.is_superuser:
		return get_object_or_404(Conference, urlname=urlname)
	else:
		return get_object_or_404(Conference, urlname=urlname, administrators=request.user)

def backend_process_form(request, urlname, formclass, id, cancel_url='../', saved_url='../', allow_new=True, allow_delete=True, breadcrumbs=None, permissions_already_checked=False, conference=None, bypass_conference_filter=False):
	if not conference:
		conference = get_authenticated_conference(request, urlname)

	if not formclass.Meta.fields:
		raise Exception("This view only works if fields are explicitly listed")

	nopostprocess = False
	newformdata = None

	if allow_new and not id:
		if formclass.form_before_new:
			if request.method == 'POST' and '_validator' in request.POST:
				# This is a postback from the *actual* form
				print("Setting newformdata 1!")
				newformdata = request.POST['_newformdata']
				instance = formclass.Meta.model(conference=conference)
			else:
				# Postback to the first step create form
				newinfo = False
				if request.method == 'POST':
					# Making the new one!
					newform = formclass.form_before_new(request.POST)
					if newform.is_valid():
						newinfo = True
				else:
					newform = formclass.form_before_new()
				if not newinfo:
					return render(request, 'confreg/admin_backend_form.html', {
						'conference': conference,
						'form': newform,
						'what': 'New {0}'.format(formclass.Meta.model._meta.verbose_name),
						'cancelurl': cancel_url,
						'breadcrumbs': breadcrumbs,
					})
				instance = formclass.Meta.model(conference=conference)
				newformdata = newform.get_newform_data()
				nopostprocess = True
		else:
			# No special form_before_new, so just create an empty instance
			instance = formclass.Meta.model(conference=conference)
	else:
		if bypass_conference_filter:
			instance = get_object_or_404(formclass.Meta.model, pk=id)
		else:
			instance = get_object_or_404(formclass.Meta.model, pk=id, conference=conference)

	if request.method == 'POST' and not nopostprocess:
		extra_error=None
		if allow_delete and request.POST['submit'] == 'Delete':
			if instance.pk:
				# Are there any associated objects here, by any chance?
				collector=NestedObjects(using='default')
				collector.collect([instance,])
				to_delete = collector.nested()
				to_delete.remove(instance)
				if to_delete:
					pieces=[unicode(to_delete[0][n]) for n in range(0, min(5, len(to_delete[0]))) if not isinstance(to_delete[0][n], list)]
					extra_error=u"This {0} cannot be deleted. It would have resulted in the following other objects also being deleted: {1}".format(formclass.Meta.model._meta.verbose_name,u', '.join(pieces))
				else:
					messages.info(request, "{0} {1} deleted.".format(formclass.Meta.model._meta.verbose_name.capitalize(), instance))
					instance.delete()
					return HttpResponseRedirect(cancel_url)
			else:
				messages.warning(request, "New {0} not deleted, object was never saved.".format(formclass.Meta.model._meta.verbose_name.capitalize()))
				return HttpResponseRedirect(cancel_url)

		form = formclass(conference, instance=instance, data=request.POST, newformdata=newformdata)
		if extra_error:
			form.add_error(None, extra_error)

		if form.is_valid():
			# We don't want to use form.save(), because it actually saves all
			# fields on the model, including those we don't care about.
			# The savem2m model, however, *does* care about the lsited fields.
			# Consistency is overrated!
			with transaction.atomic():
				if allow_new and not instance.pk:
					form.save()
				form._save_m2m()
				form.instance.save(update_fields=[f for f in form.fields.keys() if not f in ('_validator', '_newformdata') and not isinstance(form[f].field, forms.ModelMultipleChoiceField)])
				return HttpResponseRedirect(saved_url)
	else:
		form = formclass(conference, instance=instance, newformdata=newformdata)

	if instance.id:
		adminurl = urlresolvers.reverse('admin:{0}_{1}_change'.format(instance._meta.app_label, instance._meta.model_name), args=(instance.id,))
	else:
		adminurl = None
	return render(request, 'confreg/admin_backend_form.html', {
		'conference': conference,
		'form': form,
		'what': formclass.Meta.model._meta.verbose_name,
		'cancelurl': cancel_url,
		'selectize_multiple_fields': formclass.selectize_multiple_fields,
		'breadcrumbs': breadcrumbs,
		'allow_delete': allow_delete and instance.pk,
		'adminurl': adminurl,
	})

def backend_handle_copy_previous(request, formclass, restpieces, conference):
	if len(restpieces) == 1:
		# No conference selected yet, so start by doing that
		if request.method == 'POST':
			form = BackendCopySelectConferenceForm(request, conference, formclass.Meta.model, data=request.POST)
			if form.is_valid():
				return HttpResponseRedirect("{0}/".format(form.cleaned_data.get('conference').id))
		else:
			form = BackendCopySelectConferenceForm(request, conference, formclass.Meta.model)
		return render(request, 'confreg/admin_backend_copy_select_conf.html', {
			'conference': conference,
			'form': form,
			'what': formclass.Meta.model._meta.verbose_name,
			'savebutton': 'Copy',
			'cancelurl': '../',
			'breadcrumbs': [('../', formclass.Meta.model._meta.verbose_name_plural.capitalize()), ],
		})
	elif len(restpieces) == 2:
		idlist = None
		confirmed_transform_value = None
		confirmed_transform_example = None
		sourceconfid = int(restpieces[1])
		sourceconf = get_object_or_404(Conference, pk=sourceconfid, administrators=request.user)

		if request.method == "POST":
			idlist = sorted([int(k[2:]) for k,v in request.POST.items() if k.startswith('c_') and v == '1'])
			if formclass.copy_transform_form:
				# First validate the transform form
				transform_form = formclass.copy_transform_form(conference, sourceconf, data=request.POST)
				if transform_form.is_valid():
					# Transform input is valid, but is it correct?
					if request.POST.get('confirmed_transform', '') == transform_form.confirm_value():
						with transaction.atomic():
							errors = list(formclass.copy_from_conference(conference, sourceconf, idlist, transform_form))
							if errors:
								for e in errors:
									messages.error(request, e)
									transaction.set_rollback(True)
									# Fall-through and re-render the form
							else:
								return HttpResponseRedirect("../../")
					else:
						# Transform input is valid, but it has not been confirmed.
						confirmed_transform_example = formclass.get_transform_example(conference, sourceconf, idlist, transform_form)
						if confirmed_transform_example:
							confirmed_transform_value = transform_form.confirm_value()
						# Fall-through to re-render the form
			else:
				with transaction.atomic():
					errors = list(formclass.copy_from_conference(conference, sourceconf, idlist))
					if errors:
						for e in errors:
							messages.error(request, e)
						transaction.set_rollback(True)
						transform_form = None
						# Fall through and re-render our forms
					else:
						return HttpResponseRedirect("../../")

		else:
			if formclass.copy_transform_form:
				transform_form = formclass.copy_transform_form(conference, sourceconf)
			else:
				transform_form = None

		objects = formclass.Meta.model.objects.filter(conference=sourceconf)
		values = [{'id': o.id, 'vals': [getattr(o, '_display_{0}'.format(f), getattr(o, f)) for f in formclass.list_fields]} for o in objects]
		return render(request, 'confreg/admin_backend_list.html', {
			'conference': conference,
			'values': values,
			'title': formclass.Meta.model._meta.verbose_name_plural.capitalize(),
			'singular_name': formclass.Meta.model._meta.verbose_name,
			'plural_name': formclass.Meta.model._meta.verbose_name_plural,
			'headers': [formclass.get_field_verbose_name(f) for f in formclass.list_fields],
			'coltypes': formclass.coltypes,
			'return_url': '../',
			'allow_new': False,
			'allow_delete': False,
			'allow_copy_previous': False,
			'is_copy_previous': True,
			'transform_form': transform_form,
			'idlist': idlist,
			'confirmed_transform_value': confirmed_transform_value,
			'transform_example': confirmed_transform_example,
			'breadcrumbs': [
				('../../', formclass.Meta.model._meta.verbose_name_plural.capitalize()),
				('../', 'Copy {0}'.format(formclass.Meta.model._meta.verbose_name_plural.capitalize())),
			],
		})


def backend_list_editor(request, urlname, formclass, resturl, allow_new=True, allow_delete=True, conference=None):
	if not conference:
		conference = get_authenticated_conference(request, urlname)

	if resturl:
		resturl = resturl.rstrip('/')
	if resturl == '' or resturl == None:
		# Render the list of objects
		objects = formclass.Meta.model.objects.filter(conference=conference)
		values = [{'id': o.id, 'vals': [getattr(o, '_display_{0}'.format(f), getattr(o, f)) for f in formclass.list_fields]} for o in objects]
		return render(request, 'confreg/admin_backend_list.html', {
			'conference': conference,
			'values': values,
			'title': formclass.Meta.model._meta.verbose_name_plural.capitalize(),
			'singular_name': formclass.Meta.model._meta.verbose_name,
			'plural_name': formclass.Meta.model._meta.verbose_name_plural,
			'headers': [formclass.get_field_verbose_name(f) for f in formclass.list_fields],
			'coltypes': formclass.coltypes,
			'return_url': '../',
			'allow_new': allow_new,
			'allow_delete': allow_delete,
			'allow_copy_previous': formclass.allow_copy_previous,
		})

	if allow_new and resturl=='new':
		# This one is more interesting...
		return backend_process_form(request,
									urlname,
									formclass,
									None,
									allow_new=True,
									allow_delete=allow_delete,
									breadcrumbs=[('../', formclass.Meta.model._meta.verbose_name_plural.capitalize()), ],
									conference=conference)

	restpieces = resturl.split('/')
	if formclass.allow_copy_previous and restpieces[0] == 'copy':
		return backend_handle_copy_previous(request, formclass, restpieces, conference)

	# Is it an id?
	try:
		id = int(resturl)
	except ValueError:
		# No id. So we don't know. Fail.
		raise Http404()

	return backend_process_form(request,
								urlname,
								formclass,
								id,
								allow_delete=allow_delete,
								breadcrumbs=[('../', formclass.Meta.model._meta.verbose_name_plural.capitalize()), ],
								conference=conference)


#######################
# Simple editing views
#######################

def edit_conference(request, urlname):
	# Need to bypass the conference filter, since conference is not linked to
	# conference. However, the validation on urlname is already done, so there
	# is no way to access it without having the permissions in the first place.
	return backend_process_form(request,
								urlname,
								BackendConferenceForm,
								get_object_or_404(Conference, urlname=urlname).pk,
								bypass_conference_filter=True,
								allow_new=False,
								allow_delete=False)

def edit_registration(request, urlname, regid):
	return backend_process_form(request,
								urlname,
								BackendRegistrationForm,
								regid,
								allow_new=False,
								allow_delete=False)

def edit_regclasses(request, urlname, rest):
	return backend_list_editor(request,
							   urlname,
							   BackendRegistrationClassForm,
							   rest)

def edit_regtypes(request, urlname, rest):
	return backend_list_editor(request,
							   urlname,
							   BackendRegistrationTypeForm,
							   rest)

def edit_regdays(request, urlname, rest):
	return backend_list_editor(request,
							   urlname,
							   BackendRegistrationDayForm,
							   rest)

def edit_additionaloptions(request, urlname, rest):
	return backend_list_editor(request,
							   urlname,
							   BackendAdditionalOptionForm,
							   rest)

def edit_tracks(request, urlname, rest):
	return backend_list_editor(request,
							   urlname,
							   BackendTrackForm,
							   rest)

def edit_rooms(request, urlname, rest):
	return backend_list_editor(request,
							   urlname,
							   BackendRoomForm,
							   rest)

def edit_sessions(request, urlname, rest):
	return backend_list_editor(request,
							   urlname,
							   BackendConferenceSessionForm,
							   rest)

def edit_scheduleslots(request, urlname, rest):
	return backend_list_editor(request,
							   urlname,
							   BackendConferenceSessionSlotForm,
							   rest)

def edit_volunteerslots(request, urlname, rest):
	return backend_list_editor(request,
							   urlname,
							   BackendVolunteerSlotForm,
							   rest)

def edit_feedbackquestions(request, urlname, rest):
	return backend_list_editor(request,
							   urlname,
							   BackendFeedbackQuestionForm,
							   rest)

def edit_discountcodes(request, urlname, rest):
	return backend_list_editor(request,
							   urlname,
							   BackendDiscountCodeForm,
							   rest)


###
# Non-simple-editor views
###
def pendinginvoices(request, urlname):
	conference = get_authenticated_conference(request, urlname)

	return render(request, 'confreg/admin_pending_invoices.html', {
		'conference': conference,
		'invoices': {
			'Attendee invoices': Invoice.objects.filter(paidat__isnull=True, conferenceregistration__conference=conference),
			'Bulk payment invoices': Invoice.objects.filter(paidat__isnull=True, bulkpayment__conference=conference),
			'Sponsor invoices': Invoice.objects.filter(paidat__isnull=True, sponsor__conference=conference),
		},
	})


@transaction.atomic
def purge_personal_data(request, urlname):
	conference = get_authenticated_conference(request, urlname)

	if conference.personal_data_purged:
		messages.warning(request, 'Personal data for this conference has already been purged')
		return HttpResponseRedirect('../')

	if request.method == 'POST':
		exec_no_result("INSERT INTO confreg_aggregatedtshirtsizes (conference_id, size_id, num) SELECT conference_id, shirtsize_id, count(*) FROM confreg_conferenceregistration WHERE conference_id=%(confid)s AND shirtsize_id IS NOT NULL GROUP BY conference_id, shirtsize_id", {'confid': conference.id, })
		exec_no_result("INSERT INTO confreg_aggregateddietary (conference_id, dietary, num) SELECT conference_id, lower(dietary), count(*) FROM confreg_conferenceregistration WHERE conference_id=%(confid)s AND dietary IS NOT NULL AND dietary != '' GROUP BY conference_id, lower(dietary)", {'confid': conference.id, })
		exec_no_result("UPDATE confreg_conferenceregistration SET shirtsize_id=NULL, dietary='', phone='', address='' WHERE conference_id=%(confid)s", {'confid': conference.id, })
		conference.personal_data_purged = datetime.datetime.now()
		conference.save()
		messages.info(request, "Personal data purged from conference")
		return HttpResponseRedirect('../')

	return render(request, 'confreg/admin_purge_personal_data.html', {
		'conference': conference,
		'counts': exec_to_dict("""SELECT
  count(1) FILTER (WHERE shirtsize_id IS NOT NULL) AS "T-shirt size registrations",
  count(1) FILTER (WHERE dietary IS NOT NULL AND dietary != '') AS "Dietary needs",
  count(1) FILTER (WHERE phone IS NOT NULL AND phone != '') AS "Phone numbers",
  count(1) FILTER (WHERE address IS NOT NULL AND address != '') AS "Addresses"
FROM confreg_conferenceregistration WHERE conference_id=%(confid)s""", {
	'confid': conference.id,
		})[0],
	})