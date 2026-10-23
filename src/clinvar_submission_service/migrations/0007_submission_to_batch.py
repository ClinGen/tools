import django.db.models.deletion
from django.db import migrations, models


def rename_slugs(apps, schema_editor, prefix="B"):
    """Gives every batch, and its history, a slug that starts with the prefix."""
    for model_name in ("Batch", "HistoricalBatch"):
        model = apps.get_model("clinvar_submission_service", model_name)
        for row in model.objects.all():
            row.slug = prefix + row.slug[1:]
            row.save(update_fields=["slug"])


def restore_slugs(apps, schema_editor):
    """Puts back the S at the start of each slug."""
    rename_slugs(apps, schema_editor, prefix="S")


class Migration(migrations.Migration):
    dependencies = [
        ("clinvar_submission_service", "0006_standalone_record"),
    ]

    operations = [
        migrations.RenameModel("Submission", "Batch"),
        migrations.RenameModel("HistoricalSubmission", "HistoricalBatch"),
        migrations.AlterModelTable("batch", "batch"),
        migrations.RenameField("record", "submission", "batch"),
        migrations.RenameField("historicalrecord", "submission", "batch"),
        migrations.RunPython(rename_slugs, restore_slugs),
        migrations.AlterModelOptions(
            name="batch",
            options={
                "ordering": ["-added_at"],
                "verbose_name": "Batch",
                "verbose_name_plural": "Batches",
            },
        ),
        migrations.AlterModelOptions(
            name="historicalbatch",
            options={
                "get_latest_by": ("history_date", "history_id"),
                "ordering": ("-history_date", "-history_id"),
                "verbose_name": "historical Batch",
                "verbose_name_plural": "historical Batches",
            },
        ),
        migrations.AlterModelOptions(
            name="record",
            options={
                "ordering": ["batch", "local_id"],
                "verbose_name": "Record",
                "verbose_name_plural": "Records",
            },
        ),
        migrations.AlterField(
            model_name="batch",
            name="added_at",
            field=models.DateTimeField(
                auto_now_add=True,
                help_text="When the batch was received.",
                verbose_name="Added At",
            ),
        ),
        migrations.AlterField(
            model_name="batch",
            name="api_key",
            field=models.ForeignKey(
                blank=True,
                help_text="The API key of the client that sent the batch.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="batches",
                to="clinvar_submission_service.apikey",
                verbose_name="Client",
            ),
        ),
        migrations.AlterField(
            model_name="batch",
            name="behalf_org_id",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="The ClinVar ID of the organization the batch is made for.",
                null=True,
                verbose_name="On Behalf Of",
            ),
        ),
        migrations.AlterField(
            model_name="batch",
            name="clinvar_submission_id",
            field=models.CharField(
                blank=True,
                default="",
                help_text="The ID ClinVar returned, e.g., SUB999999. Blank until ClinVar accepts the batch.",
                max_length=32,
                verbose_name="ClinVar Submission ID",
            ),
        ),
        migrations.AlterField(
            model_name="batch",
            name="clinvar_updated_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When ClinVar last updated the batch's status.",
                null=True,
                verbose_name="ClinVar Updated At",
            ),
        ),
        migrations.AlterField(
            model_name="batch",
            name="last_polled_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the poller last checked ClinVar for this batch.",
                null=True,
                verbose_name="Last Polled At",
            ),
        ),
        migrations.AlterField(
            model_name="batch",
            name="latest_response",
            field=models.JSONField(
                blank=True,
                help_text="ClinVar's most recent response for the batch.",
                null=True,
                verbose_name="Latest Response",
            ),
        ),
        migrations.AlterField(
            model_name="batch",
            name="next_poll_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the poller should next check ClinVar for this batch.",
                null=True,
                verbose_name="Next Poll At",
            ),
        ),
        migrations.AlterField(
            model_name="batch",
            name="status",
            field=models.CharField(
                choices=[
                    ("not_sent_to_clinvar", "Not Sent"),
                    ("send_to_clinvar_failed", "Send Failed"),
                    ("submitted_to_clinvar", "Submitted"),
                    ("processing_at_clinvar", "Processing"),
                    ("processed_by_clinvar", "Processed"),
                    ("error_at_clinvar", "Error"),
                ],
                default="not_sent_to_clinvar",
                help_text="Where the batch is between receipt and a final ClinVar status.",
                max_length=32,
                verbose_name="Status",
            ),
        ),
        migrations.AlterField(
            model_name="batch",
            name="updated_at",
            field=models.DateTimeField(
                auto_now=True,
                help_text="When the batch was last updated.",
                verbose_name="Updated At",
            ),
        ),
        migrations.AlterField(
            model_name="historicalbatch",
            name="added_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="When the batch was received.",
                verbose_name="Added At",
            ),
        ),
        migrations.AlterField(
            model_name="historicalbatch",
            name="api_key",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                help_text="The API key of the client that sent the batch.",
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="clinvar_submission_service.apikey",
                verbose_name="Client",
            ),
        ),
        migrations.AlterField(
            model_name="historicalbatch",
            name="behalf_org_id",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="The ClinVar ID of the organization the batch is made for.",
                null=True,
                verbose_name="On Behalf Of",
            ),
        ),
        migrations.AlterField(
            model_name="historicalbatch",
            name="clinvar_submission_id",
            field=models.CharField(
                blank=True,
                default="",
                help_text="The ID ClinVar returned, e.g., SUB999999. Blank until ClinVar accepts the batch.",
                max_length=32,
                verbose_name="ClinVar Submission ID",
            ),
        ),
        migrations.AlterField(
            model_name="historicalbatch",
            name="clinvar_updated_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When ClinVar last updated the batch's status.",
                null=True,
                verbose_name="ClinVar Updated At",
            ),
        ),
        migrations.AlterField(
            model_name="historicalbatch",
            name="last_polled_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the poller last checked ClinVar for this batch.",
                null=True,
                verbose_name="Last Polled At",
            ),
        ),
        migrations.AlterField(
            model_name="historicalbatch",
            name="latest_response",
            field=models.JSONField(
                blank=True,
                help_text="ClinVar's most recent response for the batch.",
                null=True,
                verbose_name="Latest Response",
            ),
        ),
        migrations.AlterField(
            model_name="historicalbatch",
            name="next_poll_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the poller should next check ClinVar for this batch.",
                null=True,
                verbose_name="Next Poll At",
            ),
        ),
        migrations.AlterField(
            model_name="historicalbatch",
            name="status",
            field=models.CharField(
                choices=[
                    ("not_sent_to_clinvar", "Not Sent"),
                    ("send_to_clinvar_failed", "Send Failed"),
                    ("submitted_to_clinvar", "Submitted"),
                    ("processing_at_clinvar", "Processing"),
                    ("processed_by_clinvar", "Processed"),
                    ("error_at_clinvar", "Error"),
                ],
                default="not_sent_to_clinvar",
                help_text="Where the batch is between receipt and a final ClinVar status.",
                max_length=32,
                verbose_name="Status",
            ),
        ),
        migrations.AlterField(
            model_name="historicalbatch",
            name="updated_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="When the batch was last updated.",
                verbose_name="Updated At",
            ),
        ),
        migrations.AlterField(
            model_name="historicalrecord",
            name="batch",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                help_text="The batch the record is in, if any.",
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="clinvar_submission_service.batch",
                verbose_name="Batch",
            ),
        ),
        migrations.AlterField(
            model_name="record",
            name="batch",
            field=models.ForeignKey(
                blank=True,
                help_text="The batch the record is in, if any.",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="records",
                to="clinvar_submission_service.batch",
                verbose_name="Batch",
            ),
        ),
    ]
