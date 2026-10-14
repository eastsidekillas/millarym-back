from decouple import config

ENV = config("DJANGO_ENV", default="dev")

if ENV == "prod":
    from .prod import *  # noqa: F401,F403
elif ENV == "test":
    from .test import *  # noqa: F401,F403
else:
    from .dev import *  # noqa: F401,F403
