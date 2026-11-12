from django.db import migrations, models

TOOL_ID = models.CharField(
    blank=True,
    default="",
    help_text=(
        "The ID the tool that sent the record gave it, ClinVar's localID. "
        "ClinVar makes it public."
    ),
    max_length=255,
    verbose_name="Tool ID",
)


class Migration(migrations.Migration):
    dependencies = [
        ("clinvar_submission_service", "0011_record_tool_id_label"),
    ]

    operations = [
        migrations.RenameField("record", "local_id", "tool_id"),
        migrations.RenameField("historicalrecord", "local_id", "tool_id"),
        migrations.AlterField("record", "tool_id", TOOL_ID),
        migrations.AlterField("historicalrecord", "tool_id", TOOL_ID),
        migrations.AlterModelOptions(
            name="record",
            options={
                "ordering": ["tool_id"],
                "verbose_name": "Record",
                "verbose_name_plural": "Records",
            },
        ),
    ]
