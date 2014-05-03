# -*-coding: utf-8 -*-
from django.db.models import Q
from billservice.models import Account
from phonebook.models import transliterate
from lib.decorators import render_to
from django.conf import settings
import commands
import logging
log = logging.getLogger('phonebook.views')

@render_to("phonebook/lookup.html")
def num_lookup(request):
    #DAY
    num = request.GET.get('num')
    log.debug("Lookup request for number: %s" % num)

    if num is None:
        return {'error':"No number provided in GET"} 

    try: 
        account = Account.objects.get(Q(phone_m__icontains=num) | Q(phone_h__icontains=num) | Q(contactperson_phone__icontains=num))
        log.debug("Account found for number %s: %s" % (num, account))
    except Account.DoesNotExist:
        # we have no object!  do something
        log.debug("No account found for number %s" % num)
        return {'error':"No account found"}
    fio = account.fullname.split(' ')
    if (len(fio) > 1):
        fi = transliterate(fio[0]+' '+fio[1])
    log.debug("Account Surname Name: %s" % fi)
    #return {'name':transliterate(fio[0]),'phone':num}
    return {'name':account.username,'phone':num}

