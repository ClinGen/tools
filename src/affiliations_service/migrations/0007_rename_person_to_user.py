"""Renames people to users, keeping every row and its history."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("affiliations_service", "0006_optional_person_email"),
    ]

    operations = [
        # SQLite rebuilds the membership table to rename its field, and this
        # constraint names the old field, so it's dropped first and added back by the
        # next migration.
        migrations.RemoveConstraint("Membership", "as_membership_one_open_role"),
        migrations.RenameModel("Person", "User"),
        migrations.RenameModel("PersonEmail", "UserEmail"),
        migrations.RenameModel("HistoricalPerson", "HistoricalUser"),
        migrations.RenameModel("HistoricalPersonEmail", "HistoricalUserEmail"),
        migrations.RenameField("UserEmail", "person", "user"),
        migrations.RenameField("HistoricalUserEmail", "person", "user"),
        migrations.RenameField("Membership", "person", "user"),
        migrations.RenameField("HistoricalMembership", "person", "user"),
    ]
