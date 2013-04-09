# -*- coding=utf-8 -*-

from datetime import datetime

from django import forms
from django.conf import settings
from django.contrib.auth.models import User
from django.utils.translation import ugettext as _

from helpdesk.lib import send_templated_mail
from helpdesk.models import Ticket, Queue, FollowUp, Attachment, IgnoreEmail, TicketCC,\
    PreSetReply
from helpdesk.settings import HAS_TAG_SUPPORT
from django_select2 import *
from django.contrib.auth.models import User
from django.utils.encoding import smart_unicode
import copy
from billservice.models import SystemUser, Account
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Div, Submit, Reset,  HTML, Button, Row, Field, Fieldset
from crispy_forms.bootstrap import AppendedText, PrependedText, FormActions
from django.core.urlresolvers import reverse
class UserChoices(AutoModelSelect2Field):
    queryset = User.objects
    max_results = 20
    search_fields = ['username__icontains', ]
    
    def label_from_instance(self, obj):
        return u'%s %s' % (smart_unicode(obj), smart_unicode(obj.get_full_name()))


class AccountChoices(AutoModelSelect2Field):
    queryset = Account.objects
    max_results = 20
    search_fields = ['username__istartswith', 'contract__istartswith', 'fullname__icontains']

    def label_from_instance(self, obj):
        return u'%s [%s] %s' % (smart_unicode(obj.username), smart_unicode(obj.contract), smart_unicode(obj.fullname))

    
class TicketTypeForm(forms.Form):
    queuetype = forms.ModelChoiceField(label=_('Queue'), queryset = Queue.objects.all())
    
class EditTicketForm(forms.ModelForm):
    assigned_to = forms.ModelChoiceField(
        queryset=User.objects.filter(is_staff=True).order_by('username'),
        required=False,
        label=_('Assigned to'),
        help_text=_('If you assign ticket yourself, they\'ll be '
            'e-mailed details of this ticket immediately.'),
        )    
    class Meta:
        model = Ticket
        exclude = ('created', 'modified', 'status', 'on_hold', 'resolution', 'last_escalation')

class TicketForm(forms.Form):
    queue = forms.ModelChoiceField(
        label=_('Queue'),
        required=True,
        queryset=Queue.objects.all()
        )
    title = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(),
        label=_('Summary of the problem'),
        )
    owner = UserChoices(
        choices=(),
        required=False,
        label=_(u'Создал'),
        help_text=_('If you select an owner other than yourself, they\'ll be '
            'e-mailed details of this ticket immediately.'),
        widget=AutoHeavySelect2Widget(
            select2_options={
                'width': '50%',
                'placeholder': u"Поиск владельца"
            }
        )
        )
    account = AccountChoices(
        choices=(),
        required=False,
        label=_('Account'),
        widget=AutoHeavySelect2Widget(
            select2_options={
                'width': '50%',
                'placeholder': u"Поиск аккаунта по логину, договору, ФИО"
            }
        )
        )
    assigned_to = forms.ModelChoiceField(
        required=False,
        queryset = SystemUser.objects.all(),
        label=_(u'Исполнитель'),
        help_text=_('If you assign ticket yourself, they\'ll be '
            'e-mailed details of this ticket immediately.'),
        )
    due_date =  forms.DateTimeField(label=_(u'Due Date'), required = False, widget=forms.widgets.DateTimeInput(attrs={'class':'datepicker'}))
    priority = forms.ChoiceField(
        choices=Ticket.PRIORITY_CHOICES,
        required=False,
        initial='3',
        label=_('Priority'),
        help_text=_('Please select a priority carefully. If unsure, leave it '
            'as \'3\'.'),
        )


    submitter_email = forms.EmailField(
        required=False,
        label=_('Submitter E-Mail Address'),
        help_text=_('This e-mail address will receive copies of all public '
            'updates to this ticket.'),
        )

    body = forms.CharField(
        widget=forms.widgets.Textarea(attrs={'rows':5, 'class': 'input-large span9'}),
        label=_('Description of Issue'),
        required=True,
        )
    
    hidden_comment = forms.CharField(
        label=_('Hidden comment'),
        required=False,
        widget = forms.widgets.Textarea(attrs={'rows':3, 'class': 'input-large span9'})
        )
    



    


    attachment = forms.FileField(
        required=False,
        label=_('Attach File'),
        help_text=_('You can attach a file such as a document or screenshot to this ticket.'),
        )

    if HAS_TAG_SUPPORT:
        tags = forms.CharField(
            max_length=255,
            required=False,
            widget=forms.TextInput(),
            label=_('Tags'),
            help_text=_('Words, separated by spaces, or phrases separated by commas. '
                    'These should communicate significant characteristics of this '
                    'ticket'),
            )

    def save(self, user):
        """
        Writes and returns a Ticket() object
        """

        q = self.cleaned_data['queue']

        t = Ticket( title = self.cleaned_data['title'],
                    submitter_email = self.cleaned_data['submitter_email'],
                    created = datetime.now(),
                    status = Ticket.OPEN_STATUS,
                    queue = q,
                    description = self.cleaned_data['body'],
                    priority = self.cleaned_data['priority'],
                  )

        if HAS_TAG_SUPPORT:
            t.tags = self.cleaned_data['tags']

        if self.cleaned_data['assigned_to']:
            try:
                u = User.objects.get(id=self.cleaned_data['assigned_to'])
                t.assigned_to = u
            except User.DoesNotExist:
                t.assigned_to = None
        t.save()

        f = FollowUp(   ticket = t,
                        title = _('Ticket Opened'),
                        date = datetime.now(),
                        public = False,
                        comment = self.cleaned_data['body'],
                        user = user,
                     )
        if self.cleaned_data['assigned_to']:
            f.title = _('Ticket Opened & Assigned to %(name)s') % {
                'name': t.get_assigned_to
            }

        f.save()
        
        files = []
        if self.cleaned_data['attachment']:
            import mimetypes
            file = self.cleaned_data['attachment']
            filename = file.name.replace(' ', '_')
            a = Attachment(
                followup=f,
                filename=filename,
                mime_type=mimetypes.guess_type(filename)[0] or 'application/octet-stream',
                size=file.size,
                )
            a.file.save(file.name, file, save=False)
            a.save()
            
            if file.size < getattr(settings, 'MAX_EMAIL_ATTACHMENT_SIZE', 512000):
                # Only files smaller than 512kb (or as defined in 
                # settings.MAX_EMAIL_ATTACHMENT_SIZE) are sent via email.
                files.append(a.file.path)

        context = {
            'ticket': t,
            'queue': q,
            'comment': f.comment,
        }
        
        messages_sent_to = []

        if t.submitter_email:
            send_templated_mail(
                'newticket_owner',
                context,
                recipients=t.submitter_email,
                sender=q.from_address,
                fail_silently=True,
                files=files,
                )
            messages_sent_to.append(t.submitter_email)

        if t.assigned_to and t.assigned_to != user and getattr(t.assigned_to.usersettings.settings, 'email_on_ticket_assign', False) and t.assigned_to.email and t.assigned_to.email not in messages_sent_to:
            send_templated_mail(
                'assigned_to',
                context,
                recipients=t.assigned_to.email,
                sender=q.from_address,
                fail_silently=True,
                files=files,
                )
            messages_sent_to.append(t.assigned_to.email)

        if q.new_ticket_cc and q.new_ticket_cc not in messages_sent_to:
            send_templated_mail(
                'newticket_cc',
                context,
                recipients=q.new_ticket_cc,
                sender=q.from_address,
                fail_silently=True,
                files=files,
                )
            messages_sent_to.append(q.new_ticket_cc)

        if q.updated_ticket_cc and q.updated_ticket_cc != q.new_ticket_cc and q.updated_ticket_cc not in messages_sent_to:
            send_templated_mail(
                'newticket_cc',
                context,
                recipients=q.updated_ticket_cc,
                sender=q.from_address,
                fail_silently=True,
                files=files,
                )

        return t



    
class PublicTicketForm(forms.Form):
    queue = forms.ChoiceField(
        label=_('Queue'),
        required=True,
        choices=()
        )

    title = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(),
        label=_('Summary of your query'),
        )

    submitter_email = forms.EmailField(
        required=False,
        label=_('Your E-Mail Address'),
        help_text=_('We will e-mail you when your ticket is updated.'),
        )

    body = forms.CharField(
        widget=forms.Textarea(attrs={'rows':10,'cols':100}),
        label=_('Description of your issue'),
        required=True,
        help_text=_('Please be as descriptive as possible, including any '
            'details we may need to address your query.'),
        )

    priority = forms.ChoiceField(
        choices=Ticket.PRIORITY_CHOICES,
        required=True,
        initial='3',
        label=_('Urgency'),
        help_text=_('Please select a priority carefully.'),
        )

    attachment = forms.FileField(
        required=False,
        label=_('Attach File'),
        help_text=_('You can attach a file such as a document or screenshot to this ticket.'),
        )

    def save(self,owner=None):
        """
        Writes and returns a Ticket() object
        """

        q = Queue.objects.get(id=int(self.cleaned_data['queue']))

        t = Ticket(
            title = self.cleaned_data['title'],
            owner=owner,
            submitter_email = self.cleaned_data['submitter_email'],
            created = datetime.now(),
            status = Ticket.OPEN_STATUS,
            queue = q,
            description = self.cleaned_data['body'],
            priority = self.cleaned_data['priority'],
            )

        t.save()

        f = FollowUp(
            ticket = t,
            title = _('Ticket Opened Via Web'),
            date = datetime.now(),
            public = True,
            comment = self.cleaned_data['body'],
            )

        f.save()

        files = []
        if self.cleaned_data['attachment']:
            import mimetypes
            file = self.cleaned_data['attachment']
            filename = file.name.replace(' ', '_')
            a = Attachment(
                followup=f,
                filename=filename,
                mime_type=mimetypes.guess_type(filename)[0] or 'application/octet-stream',
                size=file.size,
                )
            a.file.save(file.name, file, save=False)
            a.save()
            
            if file.size < getattr(settings, 'MAX_EMAIL_ATTACHMENT_SIZE', 512000):
                # Only files smaller than 512kb (or as defined in 
                # settings.MAX_EMAIL_ATTACHMENT_SIZE) are sent via email.
                files.append(a.file.path)

        context = {
            'ticket': t,
            'queue': q,
        }

        messages_sent_to = []

        send_templated_mail(
            'newticket_owner',
            context,
            recipients=t.submitter_email,
            sender=q.from_address,
            fail_silently=True,
            files=files,
            )
        messages_sent_to.append(t.submitter_email)

        if q.new_ticket_cc and q.new_ticket_cc not in messages_sent_to:
            send_templated_mail(
                'newticket_cc',
                context,
                recipients=q.new_ticket_cc,
                sender=q.from_address,
                fail_silently=True,
                files=files,
                )
            messages_sent_to.append(q.new_ticket_cc)

        if q.updated_ticket_cc and q.updated_ticket_cc != q.new_ticket_cc and q.updated_ticket_cc not in messages_sent_to:
            send_templated_mail(
                'newticket_cc',
                context,
                recipients=q.updated_ticket_cc,
                sender=q.from_address,
                fail_silently=True,
                files=files,
                )

        return t


class UserSettingsForm(forms.Form):
    login_view_ticketlist = forms.BooleanField(
        label=_('Show Ticket List on Login?'),
        help_text=_('Display the ticket list upon login? Otherwise, the dashboard is shown.'),
        required=False,
        )

    email_on_ticket_change = forms.BooleanField(
        label=_('E-mail me on ticket change?'),
        help_text=_('If you\'re the ticket owner and the ticket is changed via the web by somebody else, do you want to receive an e-mail?'),
        required=False,
        )

    email_on_ticket_assign = forms.BooleanField(
        label=_('E-mail me when assigned a ticket?'),
        help_text=_('If you are assigned a ticket via the web, do you want to receive an e-mail?'),
        required=False,
        )

    email_on_ticket_apichange = forms.BooleanField(
        label=_('E-mail me when a ticket is changed via the API?'),
        help_text=_('If a ticket is altered by the API, do you want to receive an e-mail?'),
        required=False,
        )

    tickets_per_page = forms.IntegerField(
        label=_('Number of tickets to show per page'),
        help_text=_('How many tickets do you want to see on the Ticket List page?'),
        required=False,
        min_value=1,
        max_value=1000,
        )

    use_email_as_submitter = forms.BooleanField(
        label=_('Use my e-mail address when submitting tickets?'),
        help_text=_('When you submit a ticket, do you want to automatically use your e-mail address as the submitter address? You can type a different e-mail address when entering the ticket if needed, this option only changes the default.'),
        required=False,
        )

class EmailIgnoreForm(forms.ModelForm):
    class Meta:
        model = IgnoreEmail

class TicketCCForm(forms.ModelForm):
    class Meta:
        model = TicketCC
        exclude = ('ticket',)


class FollowUpForm(forms.ModelForm):
    
    preset_reply = forms.ModelChoiceField(queryset = PreSetReply.objects.all(), label = _("Use a Pre-set Reply"), required=False)
    def __init__(self, *args, **kwargs):
        self.helper = FormHelper()
        self.helper.form_id = 'id-followup_form'
        self.helper.form_class = 'well form-horizontal ajax form-condensed'
        self.helper.form_method = 'post'
        self.helper.form_tag = False
        self.helper.form_action = reverse("followup_edit")
        self.helper.layout = Layout(
            Fieldset(
                '',
                 'id',
                 'ticket',
                 Field('preset_reply', css_class='input-large span6'),
                'comment',
                'public',
                'new_status',

            ),    

            FormActions(
                Submit('save', _(u'Add'), css_class="btn-primary"),
                Button('close', _(u'Close'), css_class="btn-inverse close-dialog"),
            )
               
        )
        super(FollowUpForm, self).__init__(*args, **kwargs)
        
        self.fields['ticket'].widget = forms.widgets.HiddenInput()
        self.fields['comment'].widget = forms.widgets.Textarea(attrs={'rows':5, 'class': 'input-large span6'})
        
        
    class Meta:
        model = FollowUp
        exclude = ('date', 'user', 'title')