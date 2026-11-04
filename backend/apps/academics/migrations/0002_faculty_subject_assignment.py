import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0001_initial'),
        ('faculty', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='FacultySubjectAssignment',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('role', models.CharField(choices=[('TEACHER', 'Teacher'), ('INTERNAL_EXAMINER', 'Internal Examiner'), ('EXTERNAL_EXAMINER', 'External Examiner'), ('MODERATOR', 'Moderator')], default='TEACHER', help_text='Assigned academic role for this paper offering.', max_length=30)),
                ('assigned_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('faculty', models.ForeignKey(db_column='faculty_id', on_delete=django.db.models.deletion.RESTRICT, related_name='paper_assignments', to='faculty.facultyprofile')),
                ('paper_offering', models.ForeignKey(db_column='paper_offering_id', on_delete=django.db.models.deletion.RESTRICT, related_name='faculty_assignments', to='academics.paperoffering')),
            ],
            options={
                'verbose_name': 'Faculty Subject Assignment',
                'verbose_name_plural': 'Faculty Subject Assignments',
                'db_table': 'academics_faculty_subject_assignment',
            },
        ),
        migrations.AddConstraint(
            model_name='facultysubjectassignment',
            constraint=models.UniqueConstraint(fields=('faculty', 'paper_offering', 'role'), name='uk_faculty_paper_role'),
        ),
    ]
