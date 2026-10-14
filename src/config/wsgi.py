"""Configures the WSGI server."""

from django.core.wsgi import get_wsgi_application
from dotenv import load_dotenv

# Load environment variables from the .env file.
load_dotenv()

application = get_wsgi_application()
