# SPDX-License-Identifier: Apache-2.0
#
# http://nexb.com and https://github.com/nexB/scancode.io
# The ScanCode.io software is licensed under the Apache License version 2.0.
# Data generated with ScanCode.io is provided as-is without warranties.
# ScanCode is a trademark of nexB Inc.
#
# You may not use this software except in compliance with the License.
# You may obtain a copy of the License at: http://apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.
#
# Data Generated with ScanCode.io is provided on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, either express or implied. No content created from
# ScanCode.io should be considered or used as legal advice. Consult an Attorney
# for any legal advice.
#
# ScanCode.io is a free software code scanning tool from nexB Inc. and others.
# Visit https://github.com/nexB/scancode.io for support and download.

import datetime
import tempfile
import uuid
from io import StringIO
from pathlib import Path
from unittest import mock

from django.apps import apps
from django.core.management import CommandError
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from scanpipe.management.commands.graph import is_graphviz_installed
from scanpipe.management.commands.graph import pipeline_graph_dot
from scanpipe.models import Project

scanpipe_app = apps.get_app_config("scanpipe")


def task_success(run):
    run.task_exitcode = 0
    run.save()


def task_failure(run):
    run.task_output = "Error log"
    run.task_exitcode = 1
    run.save()


class ScanPipeManagementCommandTest(TestCase):
    pipeline_name = "docker"
    pipeline_class = scanpipe_app.pipelines.get(pipeline_name)

    def test_scanpipe_management_command_graph(self):
        out = StringIO()
        temp_dir = tempfile.mkdtemp()

        if not is_graphviz_installed():
            expected = "Graphviz is not installed."
            with self.assertRaisesMessage(CommandError, expected):
                call_command("graph", self.pipeline_name)
            return

        call_command("graph", self.pipeline_name, "--output", temp_dir, stdout=out)
        out_value = out.getvalue()
        self.assertIn("Graph(s) generated:", out_value)
        self.assertIn("docker.png", out_value)
        self.assertTrue(Path(f"/{temp_dir}/docker.png").exists())
        self.assertTrue(Path(f"/{temp_dir}/docker.png").exists())

    def test_scanpipe_pipelines_pipeline_graph_output_dot(self):
        output_dot = pipeline_graph_dot(self.pipeline_name, self.pipeline_class)
        self.assertIn("rankdir=TB;", output_dot)
        self.assertIn('"extract_images"[label=<<b>extract_images</b>>', output_dot)
        self.assertIn('"extract_layers"[label=<<b>extract_layers</b>>', output_dot)
        self.assertIn("extract_images -> extract_layers;", output_dot)
        self.assertIn("extract_layers -> find_images_os_and_distro;", output_dot)

    def test_scanpipe_management_command_create_project_base(self):
        out = StringIO()

        expected = "Error: the following arguments are required: name"
        with self.assertRaisesMessage(CommandError, expected):
            call_command("create-project")

        call_command("create-project", "my_project", stdout=out)
        self.assertIn("Project my_project created", out.getvalue())
        self.assertTrue(Project.objects.get(name="my_project"))

        expected = "Project with this Name already exists."
        with self.assertRaisesMessage(CommandError, expected):
            call_command("create-project", "my_project")

    def test_scanpipe_management_command_create_project_pipelines(self):
        out = StringIO()

        options = ["--pipeline", "non-existing"]
        expected = "non-existing is not a valid pipeline"
        with self.assertRaisesMessage(CommandError, expected):
            call_command("create-project", "my_project", *options)

        options = [
            "--pipeline",
            self.pipeline_name,
            "--pipeline",
            "root_filesystems",
        ]
        call_command("create-project", "my_project", *options, stdout=out)
        self.assertIn("Project my_project created", out.getvalue())
        project = Project.objects.get(name="my_project")
        expected = [
            self.pipeline_name,
            "root_filesystems",
        ]
        self.assertEqual(expected, [run.pipeline_name for run in project.runs.all()])

    def test_scanpipe_management_command_create_project_inputs(self):
        out = StringIO()

        options = ["--input-file", "non-existing"]
        expected = "non-existing not found or not a file"
        with self.assertRaisesMessage(CommandError, expected):
            call_command("create-project", "my_project", *options)

        parent_path = Path(__file__).parent
        options = [
            "--input-file",
            str(parent_path / "test_commands.py"),
            "--input-file",
            str(parent_path / "test_models.py"),
        ]
        call_command("create-project", "my_project", *options, stdout=out)
        self.assertIn("Project my_project created", out.getvalue())
        project = Project.objects.get(name="my_project")
        expected = sorted(["test_commands.py", "test_models.py"])
        self.assertEqual(expected, sorted(project.input_files))

    def test_scanpipe_management_command_create_project_execute(self):
        options = ["--execute"]
        expected = "The --execute option requires one or more pipelines."
        with self.assertRaisesMessage(CommandError, expected):
            call_command("create-project", "my_project", *options)

        pipeline = "load_inventory"
        options = [
            "--pipeline",
            pipeline,
            "--execute",
        ]

        out = StringIO()
        with mock.patch("scanpipe.models.Run.execute_task_async", task_success):
            call_command("create-project", "my_project", *options, stdout=out)

        self.assertIn("Project my_project created", out.getvalue())
        self.assertIn(f"Pipeline {pipeline} run in progress...", out.getvalue())
        self.assertIn("successfully executed on project my_project", out.getvalue())

    def test_scanpipe_management_command_add_input_file(self):
        out = StringIO()

        project = Project.objects.create(name="my_project")
        parent_path = Path(__file__).parent
        options = [
            "--input-file",
            str(parent_path / "test_commands.py"),
            "--input-file",
            str(parent_path / "test_models.py"),
        ]

        expected = "the following arguments are required: --project"
        with self.assertRaisesMessage(CommandError, expected):
            call_command("add-input", *options, stdout=out)

        options.extend(["--project", project.name])
        call_command("add-input", *options, stdout=out)
        self.assertIn("File(s) copied to the project inputs directory", out.getvalue())
        expected = sorted(["test_commands.py", "test_models.py"])
        self.assertEqual(expected, sorted(project.input_files))

        options = ["--project", project.name, "--input-file", "non-existing.py"]
        expected = "non-existing.py not found or not a file"
        with self.assertRaisesMessage(CommandError, expected):
            call_command("add-input", *options, stdout=out)

    def test_scanpipe_management_command_add_input_url(self):
        out = StringIO()

        project = Project.objects.create(name="my_project")
        parent_path = Path(__file__).parent
        options = [
            "--input-file",
            str(parent_path / "test_commands.py"),
            "--input-file",
            str(parent_path / "test_models.py"),
        ]

    def test_scanpipe_management_command_add_pipeline(self):
        out = StringIO()

        project = Project.objects.create(name="my_project")

        pipelines = [
            self.pipeline_name,
            "root_filesystems",
        ]

        options = pipelines[:]
        expected = "the following arguments are required: --project"
        with self.assertRaisesMessage(CommandError, expected):
            call_command("add-pipeline", *options, stdout=out)

        options.extend(["--project", project.name])
        call_command("add-pipeline", *options, stdout=out)
        self.assertIn("Pipeline(s) added to the project", out.getvalue())
        self.assertEqual(pipelines, [run.pipeline_name for run in project.runs.all()])

        options = ["--project", project.name, "non-existing"]
        expected = "non-existing is not a valid pipeline"
        with self.assertRaisesMessage(CommandError, expected):
            call_command("add-pipeline", *options, stdout=out)

    def test_scanpipe_management_command_show_pipeline(self):
        pipeline_names = [
            self.pipeline_name,
            "root_filesystems",
        ]

        project = Project.objects.create(name="my_project")
        for pipeline_name in pipeline_names:
            project.add_pipeline(pipeline_name)

        options = ["--project", project.name, "--no-color"]
        out = StringIO()
        call_command("show-pipeline", *options, stdout=out)
        expected = " [NOT_STARTED] docker\n" " [NOT_STARTED] root_filesystems\n"
        self.assertEqual(expected, out.getvalue())

        project.runs.filter(pipeline_name=pipeline_names[0]).update(task_exitcode=0)
        project.runs.filter(pipeline_name=pipeline_names[1]).update(task_exitcode=1)

        out = StringIO()
        call_command("show-pipeline", *options, stdout=out)
        expected = " [SUCCESS] docker\n" " [FAILURE] root_filesystems\n"
        self.assertEqual(expected, out.getvalue())

    def test_scanpipe_management_command_execute(self):
        project = Project.objects.create(name="my_project")
        options = ["--project", project.name]

        out = StringIO()
        expected = "No pipelines to run on project my_project"
        with self.assertRaisesMessage(CommandError, expected):
            call_command("execute", *options, stdout=out)

        project.add_pipeline(self.pipeline_name)

        out = StringIO()
        with mock.patch("scanpipe.models.Run.execute_task_async", task_success):
            call_command("execute", *options, stdout=out)
        expected = "Pipeline docker run in progress..."
        self.assertIn(expected, out.getvalue())
        expected = "successfully executed on project my_project"
        self.assertIn(expected, out.getvalue())

        err = StringIO()
        project.add_pipeline(self.pipeline_name)
        with mock.patch("scanpipe.models.Run.execute_task_async", task_failure):
            with self.assertRaisesMessage(SystemExit, "1"):
                call_command("execute", *options, stdout=out, stderr=err)
        expected = "Error during docker execution:"
        self.assertIn(expected, err.getvalue())
        self.assertIn("Error log", err.getvalue())

    def test_scanpipe_management_command_status(self):
        project = Project.objects.create(name="my_project")
        run = project.add_pipeline(self.pipeline_name)

        options = ["--project", project.name, "--no-color"]
        out = StringIO()
        call_command("status", *options, stdout=out)

        output = out.getvalue()
        self.assertIn("Project: my_project", output)
        self.assertIn("- CodebaseResource: 0", output)
        self.assertIn("- DiscoveredPackage: 0", output)
        self.assertIn("- ProjectError: 0", output)
        self.assertIn("[NOT_STARTED] docker", output)

        run.task_id = uuid.uuid4()
        run.save()
        out = StringIO()
        call_command("status", *options, stdout=out)
        output = out.getvalue()
        self.assertIn("[QUEUED] docker", output)

        run.task_start_date = timezone.now()
        run.log = (
            "[1611839665826870/start/1 (pid 65890)] Task finished successfully.\n"
            "[1611839665826870/extract_images/2 (pid 65914)] Task is starting.\n"
        )
        run.save()
        out = StringIO()
        call_command("status", *options, stdout=out)

        output = out.getvalue()
        self.assertIn("[RUNNING] docker", output)
        for line in run.log.split("\n"):
            self.assertIn(line, output)

        run.task_end_date = run.task_start_date + datetime.timedelta(0, 42)
        run.task_exitcode = 0
        run.save()
        out = StringIO()
        call_command("status", *options, stdout=out)
        output = out.getvalue()
        expected = f"[SUCCESS] docker (executed in {run.execution_time} seconds)"
        self.assertIn(expected, output)

    def test_scanpipe_management_command_output(self):
        project = Project.objects.create(name="my_project")

        out = StringIO()
        options = ["--project", project.name, "--no-color"]
        call_command("output", *options, stdout=out)
        out_value = out.getvalue().strip()
        self.assertTrue(out_value.endswith(".json"))
        filename = out_value.split("/")[-1]
        self.assertIn(filename, project.output_root)

        out = StringIO()
        options.extend(["--format", "csv"])
        call_command("output", *options, stdout=out)
        out_value = out.getvalue().strip()
        for output_file in out_value.split("\n"):
            filename = out_value.split("/")[-1]
            self.assertIn(filename, project.output_root)

        out = StringIO()
        options.extend(["--format", "WRONG"])
        message = (
            "Error: argument --format: invalid choice: 'WRONG' "
            "(choose from 'json', 'csv', 'xlsx')"
        )
        with self.assertRaisesMessage(CommandError, message):
            call_command("output", *options, stdout=out)

    def test_scanpipe_management_command_delete_project(self):
        project = Project.objects.create(name="my_project")
        work_path = project.work_path
        self.assertTrue(work_path.exists())

        out = StringIO()
        options = ["--project", project.name, "--no-color", "--no-input"]
        call_command("delete-project", *options, stdout=out)
        out_value = out.getvalue().strip()

        expected = "All the my_project project data have been removed."
        self.assertEqual(expected, out_value)

        self.assertFalse(Project.objects.filter(name="my_project").exists())
        self.assertFalse(work_path.exists())
