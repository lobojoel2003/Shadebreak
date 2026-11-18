"""Create a demo crew with a sample forecast, a planned day and a text history.

    python manage.py seed_demo --password choose-one

The forecast is sample data (labelled as such in the app), shaped like a hot
summer day in Phoenix, so the demo works without network access.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from crews.models import Assignment, CheckIn, Clothing, Crew, Experience, Exposure, JobSite, Worker, Workload
from crews.services.planning import ensure_workday, plan_workday
from crews.services.sample import load_sample_forecast
from messaging.delivery import deliver
from messaging.inbound import handle_inbound, record_reply
from messaging.models import Message

CREW_NAME = "Desert Bloom Landscaping (demo)"


class Command(BaseCommand):
    help = "Create a demo crew, sites, workers, a sample forecast and a day of texts."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="demo")
        parser.add_argument("--password", required=True)
        parser.add_argument("--date", help="Day to plan (YYYY-MM-DD). Defaults to today in Phoenix.")
        parser.add_argument(
            "--clock",
            default=None,
            help="Local time (HH:MM) the text history runs up to. Defaults to the current time.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        user_model = get_user_model()
        user, _ = user_model.objects.get_or_create(username=options["username"])
        user.set_password(options["password"])
        user.save()

        Crew.objects.filter(name=CREW_NAME).delete()
        crew = Crew.objects.create(
            name=CREW_NAME,
            lead_name="Marisol Reyes",
            lead_phone="+16025550100",
            timezone="America/Phoenix",
            language="en",
        )
        crew.leads.add(user)
        tz = crew.tz
        day = date.fromisoformat(options["date"]) if options["date"] else crew.today()
        if options["clock"]:
            try:
                clock = time.fromisoformat(options["clock"])
            except ValueError as exc:
                raise CommandError("--clock must look like 10:30") from exc
            now = datetime.combine(day, clock, tzinfo=tz)
        else:
            now = timezone.now()

        park = JobSite.objects.create(
            crew=crew,
            name="Camelback Office Park",
            address="2400 E Camelback Rd, Phoenix, AZ 85016",
            latitude=Decimal("33.5092"),
            longitude=Decimal("-112.0302"),
            exposure=Exposure.SUN,
            workload=Workload.HEAVY,
            clothing=Clothing.STANDARD,
            shift_start=time(5, 30),
            shift_end=time(14, 0),
            weekdays="0123456",
            water_location="Two 10-gallon coolers on the truck tailgate, refilled at 9:00 and 12:00",
            shade_location="Pop-up canopy at the north parking lot, seats for 6",
            nearest_hospital="Emergency room 2.4 mi south on 24th St (call 911 first)",
            timezone="America/Phoenix",
            nws_place="Phoenix, AZ",
            elevation_m=340,
        )
        fields = JobSite.objects.create(
            crew=crew,
            name="Mesa Ballfields",
            address="Mesa, AZ",
            latitude=Decimal("33.4152"),
            longitude=Decimal("-111.8315"),
            exposure=Exposure.PARTIAL,
            workload=Workload.MODERATE,
            shift_start=time(6, 0),
            shift_end=time(14, 30),
            weekdays="0123456",
            water_location="Cooler by the dugout",
            shade_location="Dugouts and the snack-bar awning",
            nearest_hospital="Urgent care 1.1 mi east on Main St",
            timezone="America/Phoenix",
            nws_place="Mesa, AZ",
            elevation_m=380,
        )
        long_ago = day - timedelta(days=400)
        people = [
            ("Luis Ortega", "+16025550111", "es", Experience.ACCLIMATIZED, long_ago, park),
            ("Ana Torres", "+16025550112", "es", Experience.NEW, day - timedelta(days=1), park),
            ("Jake Miller", "+16025550113", "en", Experience.ACCLIMATIZED, long_ago, park),
            ("Darnell Brooks", "+16025550114", "en", Experience.RETURNING, day, park),
            ("Rosa Delgado", "+16025550115", "es", Experience.ACCLIMATIZED, long_ago, fields),
            ("Marco Ruiz", "+16025550116", "es", Experience.NEW, day, fields),
            ("Kim Nguyen", "+16025550117", "en", Experience.ACCLIMATIZED, long_ago, fields),
        ]
        workers = {}
        for name, phone, language, experience, start, site in people:
            workers[name] = Worker.objects.create(
                crew=crew,
                name=name,
                phone=phone,
                language=language,
                experience=experience,
                start_date=start,
                site=site,
                sms_opt_in=True,
            )
        Worker.objects.filter(pk=workers["Luis Ortega"].pk).update(buddy=workers["Ana Torres"])
        Worker.objects.filter(pk=workers["Ana Torres"].pk).update(buddy=workers["Luis Ortega"])

        yesterday = day - timedelta(days=1)
        load_sample_forecast(park, yesterday, high_c=42.5, days=2)
        load_sample_forecast(fields, yesterday, high_c=41.5, days=2)

        # Yesterday: Ana's first hot day, so today she is on day 2 of her ramp.
        past, _ = ensure_workday(park, yesterday)
        Assignment.objects.filter(workday=past).exclude(worker=workers["Ana Torres"]).delete()
        plan_workday(past, now=datetime.combine(yesterday, time(4, 0), tzinfo=tz), notify=False)

        start_of_day = datetime.combine(day, time(4, 30), tzinfo=tz)
        for site in (park, fields):
            workday, _ = ensure_workday(site, day)
            plan_workday(workday, now=start_of_day)

        self._play_out_morning(crew, day, now)
        self.stdout.write(
            self.style.SUCCESS(f"Demo crew ready for {day}. Sign in as {options['username']!r}.")
        )

    def _play_out_morning(self, crew: Crew, day: date, now: datetime) -> None:
        """Send the texts due before ``now`` and answer the check-ins.

        Every buddy answers within a few minutes except the most recent
        check-in, which goes unanswered so the demo shows an escalation.
        """
        from messaging.escalation import escalate_missed

        queued = Message.objects.filter(crew=crew, status=Message.Status.QUEUED, send_at__lte=now)
        due = list(
            CheckIn.objects.filter(workday__site__crew=crew, workday__date=day, due_at__lte=now).order_by(
                "due_at"
            )
        )
        unanswered = due[-1].pk if due else None
        for message in queued.order_by("send_at"):
            deliver(message, now=message.send_at)
            if message.kind != Message.Kind.CHECKIN or message.checkin_id == unanswered:
                continue
            answered = message.send_at + timedelta(minutes=3)
            result = handle_inbound(message.to_number, "1", now=answered)
            if result.reply:
                reply = record_reply(result, message.to_number, result.crew_id, sent=True)
                Message.objects.filter(pk=reply.pk).update(send_at=answered, sent_at=answered)
        escalate_missed(now=now)
