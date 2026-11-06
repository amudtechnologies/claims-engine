from django.apps import AppConfig


class JudicialDepositsConfig(AppConfig):
    name = 'judicial_deposits'

    def ready(self):
        from home.radars import register

        from .radar import spec

        register(spec)
